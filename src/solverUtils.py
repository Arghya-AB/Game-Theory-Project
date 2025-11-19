
import networkx as nx
from itertools import product
import logging

from z3 import Real,Int, Sum, sat,unsat,And, Implies, Solver, Optimize , is_expr

logger = logging.getLogger(__name__)

def compute_route_cost(graph, route_edges):
    """Helper Function to compute Route Costs"""
    cost_terms = []
    for u, v, key in route_edges:
        f_e = graph[u][v][key]['f_e']
        k = graph[u][v][key]['k']
        price = graph[u][v][key]['price']
        cost_terms.append(k * f_e + price)
    if any([is_expr(cost_term) for cost_term in cost_terms]):
        return Sum(cost_terms)
    return sum(cost_terms)

def compute_route_price(graph, route_edges):
    """Compute only the Ticket prices for each route"""
    price_terms = []
    for u, v, key in route_edges:
        price = graph[u][v][key]['price']
        price_terms.append(price)
    if any([is_expr(price_term) for price_term in price_terms]):
        return Sum(price_terms)
    return sum([float(price_term) for price_term in price_terms])
    
def getAllPossibleRoutes(graph:nx.MultiGraph,
                        demands: list[dict], 
                        max_hops=4) -> list[list[list]]:
    """
    Finds all simple paths (list of edges) for all demands within max_hops, 
    considering all parallel edges in the MultiGraph.
    Returns:
        list of list of lists: R_ij = [[Path1, Path2, ...], [PathA, PathB, ...], ...] 
                                where each Path is a list of edges (u, v, key).
    """
    R_ij = []
    # Constraint: Limit the number of alternative routes
    MAX_ROUTES_PER_DEMAND = 6 
    PERSONAL_CAP = 500 # if no route travel at own expense :(
    PERSONAL_PRICE = 100
    # Iterate over the list of demand dictionaries
    for demand in demands:
        all_edge_paths_for_demand = []
        s = demand['s']
        t = demand['t']
        # if source or destination not in graph add edge
        if s not in graph or t not in graph:
            node_paths = []
        else:
            # 1. Find all node paths within the cutoff
            node_paths = list(nx.all_simple_paths(graph, source=s, target=t, cutoff=max_hops)) 

        if not node_paths:
            # Add default edge if no path exists
            # Define the attributes for the new edge
            default_attr = {'k': 1, 'capacity': PERSONAL_CAP, 'price': PERSONAL_PRICE, 'color': 'personal'}
            default_key = f"auto_{s}_{t}" # Create a unique key
            # Add the new edge to the graph
            graph.add_edge(s, t, key=default_key, **default_attr)
            # The route is just this single edge
            default_route = [(s, t, default_key)]
            # Append the list of one route to the edge paths for this demand
            all_edge_paths_for_demand.append(default_route)
            R_ij.append(all_edge_paths_for_demand)
            continue
        else:
            min_length = min(len(sublist) for sublist in node_paths)
            # prune duplicates and also len of paths greater than min_length
            # reason: if A-B exists why take A-C-D-B
            node_paths = [list(sublist_tuple) 
                        for sublist_tuple in set(tuple(sublist) for sublist in node_paths if len(sublist) == min_length)]
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
                    edge_options.append((u, v, key))
                temp_list.append(edge_options)
            
            # 3. Use itertools.product to combine all parallel edge options
            route_combinations = list(product(*temp_list))
            # Convert the tuple of edges into a list of edges
            final_edge_paths = [list(path_tuple) for path_tuple in route_combinations]
            # Append all discovered edge paths for this node sequence
            all_edge_paths_for_demand.extend(final_edge_paths)
            
        # Limit the alternative routes
        # Choose the first MAX_ROUTES_PER_DEMAND paths
        R_ij.append(all_edge_paths_for_demand[:MAX_ROUTES_PER_DEMAND])
        
    return R_ij

def addVarsForSolver(graph, R_ij):
    """
    Adds inplace Z3 flow variables (f_e) to the graph and returns flow variables f_R for the routes, 
    and handles missing price data.

    Returns:
               f_R_vars is a list of list of Real Z3 variables (f_R).
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
        # 1b. Handle null price: if price is missing, add an Real variable
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
        
    return  f_R_vars

### Helper function to add Constraints to the solver 

def addC1C2Constraints(graph, R_ij, f_R_vars, solver):
    """Add Route flow Conservation and edge capacity Constraints"""
    PRICE_MIN = 5
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
                if any(edge_u == u and edge_v == v and edge_key == key for edge_u, edge_v, edge_key in route_edges):
                    sum_f_R_on_e.append(f_R_i_vars[j])
        if not sum_f_R_on_e:            
            # If no routes use this edge, the flow f_e must be zero.
            solver.add(f_e == 0)
        else:
            # If routes exist throuh e, the flow is the sum of those route flows
            # we will add constraint only if an expr on sum_f_R_on_e it will always be unsat.
            if is_expr(Sum(sum_f_R_on_e)):
                solver.add(f_e == Sum(sum_f_R_on_e))
        
        # C2: Capacity constraint: f_e <= e.capacity for all e in E
        f_e = data['f_e']
        capacity = data.get('capacity', Int(500)) # Use a large number if capacity is missing
        solver.add(0 <= f_e)
        solver.add(f_e <= capacity)

        # Price Cant be Negative: price >= 0 for all e in E
        price = data['price']
        if is_expr(price):
            solver.add(price >= PRICE_MIN)

def addC3C4Constraints(graph, R_ij,f_R_vars,demands,solver):
    """Adds C3C4 Constraints to the Solver"""
    T_i_vars = [] 
    TOLERANCE_FLOW = 1
    TOLERANCE_COST = 5
    for i, demand in enumerate(demands):
        if demand["s"] not in graph or demand["t"] not in graph:
            continue 
        # 1. C3: Demand conservation
        d_i = demand["d"]
        f_R_sum = Sum(f_R_vars[i])
        solver.add(f_R_sum == d_i)
        
        # 2. Define the minimum cost variable T_i for this demand group
        T_i = Real(f"T_{i}") 
        T_i_vars.append(T_i)
        
        # 3. Wardrop's Conditions (C4 & C5)
        f_R_i_vars = f_R_vars[i]
        demand_routes = R_ij[i]
        
        for j, route_edges in enumerate(demand_routes):
            f_R = f_R_i_vars[j]
            cost_R = compute_route_cost(graph, route_edges)
            price_R = compute_route_price(graph, route_edges)
            # C4 (Equality for Used Routes): 
            # If a flow is strictly positive (f_R > 0), its cost must equal the minimum cost (T_i).            
            # Use a small tolerance for "strictly positive" for Implies
            solver.add(Implies(
                f_R >= TOLERANCE_FLOW,
                And(cost_R <= T_i + TOLERANCE_COST, cost_R >= T_i - TOLERANCE_COST)
            ))
            # C5 (): 
            # All routes not used must have ticket price(cost of travelling alone) > cost of any of the used Route
            solver.add(Implies(
                f_R <= TOLERANCE_FLOW,
                And(price_R >= T_i - TOLERANCE_COST)
            )) 

def addSimpleC3C4(graph, R_ij,f_R_vars,demands,solver):
    """Adds Fallback C3C4 if above C3C4 fave unsat"""
    T_i_vars = [] 
    # TOLERANCE_FLOW = 1
    TOLERANCE_COST = 5
    for i, demand in enumerate(demands):
        if demand["s"] not in graph or demand["t"] not in graph:
            continue 
        # 1. C3: Demand conservation
        d_i = demand["d"]
        f_R_sum = Sum(f_R_vars[i])
        solver.add(f_R_sum == d_i)
        
        # 2. Define the minimum cost variable T_i for this demand group
        T_i = Real(f"T_{i}") 
        T_i_vars.append(T_i)
        
        # 3. Wardrop's Conditions (C4 & C5)
        f_R_i_vars = f_R_vars[i]
        demand_routes = R_ij[i]
        
        for j, route_edges in enumerate(demand_routes):
            cost_R = compute_route_cost(graph, route_edges)
            # price_R = compute_route_price(graph, route_edges)
            # C4 (Equality for Used Routes): # fallback all routes used
            solver.add(
                And(cost_R <= T_i + TOLERANCE_COST, cost_R >= T_i - TOLERANCE_COST)
            )

def addConstraints(graph, R_ij, f_R_vars, demands, solver):
    """ Adds constraints to the solver """

    addC1C2Constraints(graph, R_ij, f_R_vars, solver)
    addC3C4Constraints(graph, R_ij,f_R_vars,demands,solver)    
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
            cost_R = compute_route_cost(graph, route_edges)
            # Calculate the total term for the objective: f_R * Route_Cost 
            objective_term = f_R * cost_R
            all_terms.append(objective_term)
    # Sum all objective terms to get the final function F
    F_expr = Sum(all_terms)
    return F_expr


def UpdateGraphAndGetSolution(graph, model, f_R_vars):
    """Update the graph with model evaluations"""
    # 1. Prepare solution dict
    solution = {}
    # Retrieve f_R values and convert to long
    f_R_vals = [[model.evaluate(f_R).as_decimal(5) if is_expr(f_R) else f_R for f_R in f_R_list] for f_R_list in f_R_vars]
    solution["f_R_vals"] = f_R_vals

    # 2. Update graph with solved f_e and price values
    for u, v, key, data in graph.edges(keys=True, data=True):
        # Update f_e
        f_e_var = data['f_e']
        if is_expr(f_e_var):
            data['f_e'] = model.evaluate(f_e_var).as_decimal(5)

        # Update price (if it was a Z3 variable)
        price_var = data['price']
        if is_expr(price_var):
            data['price'] = model.evaluate(price_var).as_decimal(5)
    # 3. Add other Z3 variables to solution
    # solution["solved_vars"] = {str(d): model[d] for d in model}

    return solution