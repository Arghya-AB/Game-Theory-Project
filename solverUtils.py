
import networkx as nx
from itertools import product
from collections import defaultdict
from enum import Enum

from z3 import Real,Int, Sum, sat,unsat,And, Implies, Solver, Optimize , is_expr

def compute_route_cost(route_edges, graph):
    cost_terms = []
    for u, v, key, data_dict in route_edges:
        edge_data = graph[u][v][key]
        f_e = edge_data['f_e']
        k = edge_data['k']
        price = edge_data['price']
        cost_terms.append(k * f_e + price)
    if any([is_expr(cost_term) for cost_term in cost_terms]):
        return Sum(cost_terms)
    return sum(cost_terms)

def getAllPossibleRoutes(graph, demands, max_hops=3):
    """
    Finds all simple paths (list of edges) for all demands within max_hops, 
    considering all parallel edges in the MultiGraph.
    Returns:
        list of list of lists: R_ij = [[Path1, Path2, ...], [PathA, PathB, ...], ...] 
                                where each Path is a list of edges (u, v, key, data_dict).
    """
    R_ij = []
    
    # Constraint: Limit the number of alternative routes
    MAX_ROUTES_PER_DEMAND = 8 
    
    # Iterate over the list of demand dictionaries
    for demand in demands:
        all_edge_paths_for_demand = []
        s = demand['s']
        t = demand['t']
        
        # 1. Find all node paths within the cutoff
        node_paths = list(nx.all_simple_paths(graph, source=s, target=t, cutoff=max_hops)) 

        if not node_paths:
            # Add default edge if no path exists
            # Define the attributes for the new edge
            default_attr = {'k': 1.0, 'capacity': 200, 'price': 100, 'color': 'personal'}
            default_key = f"auto_{s}_{t}" # Create a unique key
            
            # Add the new edge to the graph
            graph.add_edge(s, t, key=default_key, **default_attr)
            
            # The route is just this single edge
            default_route = [(s, t, default_key, default_attr)]
            
            # Append the list of one route to the edge paths for this demand
            all_edge_paths_for_demand.append(default_route)
            
            R_ij.append(all_edge_paths_for_demand)
            continue

        # 2. Iterate over each node path and generate edge combinations
        for path in node_paths:
            temp_list = []

            # Iterate over consecutive nodes in the path: (path[i], path[i+1])
            for i in range(len(path) - 1):
                u = path[i]
                v = path[i+1]
                
                parallel_edges = graph[u][v]
                edge_options = []
                
                # Iterate through all parallel edges between u and v
                for key, data_dict in parallel_edges.items():
                    edge_options.append((u, v, key, data_dict))
                
                temp_list.append(edge_options)
            
            # 3. Use itertools.product to combine all parallel edge options
            route_combinations = list(product(*temp_list))
            
            # Convert the tuple of edges into a list of edges
            final_edge_paths = [list(path_tuple) for path_tuple in route_combinations]
            
            # Append all discovered edge paths for this node sequence
            all_edge_paths_for_demand.extend(final_edge_paths)
            
        # Limit the alternative routes to 10 
        # Choose the first MAX_ROUTES_PER_DEMAND paths
        R_ij.append(all_edge_paths_for_demand[:MAX_ROUTES_PER_DEMAND])
        
    return graph, R_ij

def addVarsForSolver(graph, R_ij):
    """
    Adds Z3 flow variables (f_e and f_R) to the graph and routes, 
    and handles missing price data.

    Returns:
        tuple: (updated_graph, f_R_vars) 
               f_R_vars is a list of list of Int Z3 variables (f_R).
    """
    
    # List to store the Z3 route flow variables (f_R)
    f_R_vars = []

    # 1. Add f_e and handle e.price for edges in the graph
    for u, v, key, data in graph.edges(keys=True, data=True):
        
        # 1a. Add f_e variable (Real type)
        color = data.get('color', 'personal')
        # Create a unique name: e.g., 'f_A-B-red'
        f_e_name = f"f_{u}-{v}-{color}"
        f_e_var = Real(f_e_name)
        
        # Add the f_e variable to the edge data
        data['f_e'] = f_e_var
        
        # 1b. Handle null price: if price is missing, add an Int variable
        if data.get('price') is None:
            price_name = f"p_{u}-{v}-{color}"
            price_var = Real(price_name)
            # Add the Z3 variable for price to the edge data
            data['price'] = price_var

    # 2. Add f_R variables for each route
    for i, demand_routes in enumerate(R_ij):
        # List to hold flow variables for all routes of the current demand i
        demand_f_R_vars = []
        for j, route in enumerate(demand_routes):
            # Create a unique name for the route flow: e.g., 'flow_0_1' (Demand 0, Route 1)
            f_R_name = f"flow_{i}_{j}"
            f_R_var = Real(f_R_name)
            
            demand_f_R_vars.append(f_R_var)
            
        f_R_vars.append(demand_f_R_vars)
        
    return graph, f_R_vars

def addConstraints(graph, R_ij, f_R_vars, demands, solver):
    """ Adds constraints to the solver """
    T_i_vars = [] 
    TOLERANCE_FLOW = 1
    TOLERANCE_COST = 5

    # C1: Edge flow definition: Sum_R_flow_R = f_e for all e in E
    # Iterate over all edges in the graph
    for u, v, key, data in graph.edges(keys=True, data=True):
        f_e = data['f_e']
        sum_f_R_on_e = []
        
        # Iterate over all demands (i) and their routes (R_i)
        for i, demand_routes in enumerate(R_ij):
            f_R_i_vars = f_R_vars[i]
            
            # Check which routes R use edge e
            for j, route_edges in enumerate(demand_routes):
                if any(edge_u == u and edge_v == v and edge_key == key for edge_u, edge_v, edge_key, _ in route_edges):
                    sum_f_R_on_e.append(f_R_i_vars[j])
        
        if not sum_f_R_on_e:            
            # If no routes use this edge, the flow f_e must be zero.
            solver.add(f_e == 0)
        else:
            # If routes exist, the flow is the sum of those route flows.
            solver.add(f_e == Sum(sum_f_R_on_e))
        
        # C2: Capacity constraint: f_e <= e.capacity for all e in E
        f_e = data['f_e']
        capacity = data.get('capacity', Int(500)) # Use a large number if capacity is missing
        solver.add(f_e <= capacity)
    
    for i, demand in enumerate(demands):
        # 1. C3: Demand conservation
        d_i = demand["d"]
        f_R_sum = Sum(f_R_vars[i])
        solver.add(f_R_sum == d_i)
        
        # 2. Define the minimum cost variable T_i for this demand group
        T_i = Real(f"T_{i}") 
        T_i_vars.append(T_i)
        
        # # Add bounds for T_i (efficiency)
        # solver.add(T_i >= 0)
        # solver.add(T_i <= 100) 

        # 3. Wardrop's Conditions (C4 & C5)
        f_R_i_vars = f_R_vars[i]
        demand_routes = R_ij[i]
        
        for j, route_edges in enumerate(demand_routes):
            f_R = f_R_i_vars[j]
            cost_R = compute_route_cost(route_edges, graph) # Pass graph to helper
            
            # C5 (Cost is never less than minimum): 
            # All routes must have a cost >= T_i.
            solver.add(cost_R >= T_i) 
            
            # C4 (Equality for Used Routes): 
            # If a flow is strictly positive (f_R > 0), its cost must equal the minimum cost (T_i).            
            # Use a small tolerance for "strictly positive" for Implies
            solver.add(Implies(
                f_R >= TOLERANCE_FLOW,
                And(cost_R <= T_i + TOLERANCE_COST, cost_R >= T_i - TOLERANCE_COST)
            ))
            # solver.add(And(cost_R <= T_i + TOLERANCE_COST, cost_R >= T_i - TOLERANCE_COST))
        
    #  Add Non-negativity Constraint for all route flows (f_R)
    for f_R_list in f_R_vars:
        for f_R in f_R_list:
            solver.add(f_R >= 0)

def getObjectiveExpr(graph, R_ij, f_R_vars):
    """
    Constructs the Z3 expression for the objective function F (Total System Cost).
        returns z3.ArithRef: The Z3 expression.
    """
    
    all_terms = []

    for i, demand_routes in enumerate(R_ij):
        f_R_i_vars = f_R_vars[i]
        
        for j, route_edges in enumerate(demand_routes):
            f_R = f_R_i_vars[j] # The specific Z3 variable f_R
            
            # Calculate the cost for the route R: sum_e_in_R ((e.k)f_e + e.price)
            route_cost_terms = []
            
            # Iterate over edges e in route R
            for u, v, key, data_dict in route_edges:
                
                # Retrieve the edge data dictionary from the graph (ensures current data)
                edge_data = graph[u][v][key] 
                
                f_e = edge_data['f_e']
                k = edge_data['k'] # e.k
                price = edge_data['price'] # e.price
                
                # Term is: (e.k) * f_e + e.price
                cost_term = k * f_e + price
                route_cost_terms.append(cost_term)
            
            # Route Cost = Sum(cost_terms)
            route_cost = Sum(route_cost_terms)
            
            # Calculate the total term for the objective: f_R * Route_Cost 
            objective_term = f_R * route_cost
            all_terms.append(objective_term)
            
    # Sum all objective terms to get the final function F
    F_expr = Sum(all_terms)
    
    return F_expr

def optimizeObjective(graph, R_ij, f_R_vars, demands, solver):
    """Optimize using z3 under constraints"""
    # first lets estimate the f_R when routes cost fully determined/ To cut solution space
    for i, routes in enumerate(R_ij):
        route_costs = [compute_route_cost(j, graph) for j in routes]
        if any([is_expr(route)==True for route in route_costs]):
            continue
        else:
            total = sum(route_costs) 
            # this is the total spend by all source-demand commuters
            # set f_R_vars for this demand to be proportional wrt total costs of all
            # basically if the new edge addition does not enable new routes why f_R should be a variable for it just calculate it directly.
            f_R_vars[i] = [route_cost / total for route_cost in route_costs]
    solver.push()
    addConstraints(graph, R_ij, f_R_vars, demands, solver)
    # Add Objective Function
    objective = getObjectiveExpr(graph, R_ij, f_R_vars)
    h = solver.minimize(objective)
    if solver.check() == sat:
        model = solver.model()
        solver.pop()
        return model, True
    else:
        solver.pop()
        return None, False 

def setPricesHighToLow(graph, R_ij, f_R_vars, demands, solver):
    """Set Prices high to low till sat or iteration over"""
    P_MIN = 5
    P_MAX = 120
    P_DELTA = 5
    p_current = P_MAX
    isSat = sat
    model = None
    # first lets estimate the f_R when routes cost fully determined/ To cut solution space
    for i, routes in enumerate(R_ij):
        route_costs = [compute_route_cost(j, graph) for j in routes]
        if any([is_expr(route_cost)==True for route_cost in route_costs]):
            continue
        else:
            total = sum(route_costs) 
            f_R_vars[i] = [route_cost / total for route_cost in route_costs]
    # keep decreasing till sat assignment or p_min hit keep while condition is sat 
    # because before any assertion solver gives sat but we want the loop to run at least once
    while(isSat == sat and p_current >= P_MIN):
        # make graph copy
        graph_copy = graph.copy()
        # update not set prices to p_current
        for u, v, data in graph_copy.edges(data=True):
            if 'price' in data and is_expr(data['price']):
                data['price'] = p_current
        solver.push()
        addConstraints(graph_copy, R_ij, f_R_vars, demands, solver)
        # Add Objective Function
        objective = getObjectiveExpr(graph_copy, R_ij, f_R_vars)
        h = solver.minimize(objective)
        isSat = solver.check()
        if isSat == unsat: # Not satisfied even at high price
            solver.pop()
            break
        else:
            model = solver.model() 
            solver.pop() # check sat at a lower price
            p_current -= P_DELTA

    if isSat == sat:
        return model, True
    else:
        return model, False  

class Strategy(Enum):
    OPTIMIZE = optimizeObjective
    HIGHTOLOW = setPricesHighToLow

def trySolvingFeasibility(strategy, graph, R_ij, f_R_vars, demands, solver) :
    """Try solving Feasibility using a some Strategy """
    model, isSolved = strategy(graph,R_ij, f_R_vars, demands, solver)
    return model, isSolved


def getUpdatedGraphAndSolution(graph, model, f_R_vars):
    """Update the graph with model evaluations"""
    # 1. Prepare solution dict
    solution = {}

    # Retrieve f_R values and convert to long
    f_R_vals = [[model.evaluate(f_R).as_long() for f_R in f_R_list] for f_R_list in f_R_vars]
    solution["f_R_vals"] = f_R_vals
    # solution["objective_val"] = h.value()
        
    # 2. Update graph with solved f_e and price values
    for u, v, key, data in graph.edges(keys=True, data=True):
        # Update f_e
        f_e_var = data['f_e']
        if is_expr(f_e_var):
            data['f_e'] = model.evaluate(f_e_var)
        else:
            data['f_e'] = None

        # Update price (if it was a Z3 variable)
        price_var = data['price']
        if is_expr(price_var):
            data['price'] = model.evaluate(price_var)
        else:
            data['price'] = None

    # 3. Add other Z3 variables to solution
    # solution["solved_vars"] = {str(d): model[d] for d in model}

    return graph, solution