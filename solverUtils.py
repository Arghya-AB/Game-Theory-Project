
import networkx as nx
from itertools import product
from collections import defaultdict
from z3 import Real,Int, Sum, sat, Implies, Solver, Optimize  

def getAllPossibleRoutes(graph, demands, max_hops=3):
    """
    Finds all simple paths (list of edges) for all demands within max_hops, 
    considering all parallel edges in the MultiGraph.
    Returns:
        list of list of lists: R_ij = [[Path1, Path2, ...], [PathA, PathB, ...], ...] 
                                where each Path is a list of edges (u, v, key, data_dict).
    """
    R_ij = []
    
    # --- Constraint: Limit the number of alternative routes ---
    MAX_ROUTES_PER_DEMAND = 5 
    
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
            default_attr = {'k': 0.8, 'capacity': 200, 'price': 100, 'color': 'personal'}
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
        
    return R_ij

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
        color = data.get('color', 'default')
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
            
            # --- Calculate the cost for the route R: sum_e_in_R ((e.k)f_e + e.price) ---
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
            
            # --- Calculate the total term for the objective: f_R * Route_Cost ---
            objective_term = f_R * route_cost
            all_terms.append(objective_term)
            
    # Sum all objective terms to get the final function F
    F_expr = Sum(all_terms)
    
    return F_expr