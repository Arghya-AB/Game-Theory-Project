import argparse
from experiment import runExperiments 
from graphParser import parseGraph, writeGraphToJSON, parseRoutes
from z3 import Real,Int, Sum, sat, Implies,And, Optimize, is_expr 
from solverUtils import getAllPossibleRoutes, addVarsForSolver, getObjectiveExpr
import networkx as nx

# Assuming addVarsForSolver and getObjectiveExpr are defined elsewhere

# Helper function to compute route cost (e.k * f_e + e.price)
def compute_route_cost(route_edges, graph):
    cost_terms = []
    for u, v, key, data_dict in route_edges:
        edge_data = graph[u][v][key]
        f_e = edge_data['f_e']
        k = edge_data['k']
        price = edge_data['price']
        cost_terms.append(k * f_e + price)
    return Sum(cost_terms)

def solveUnknownPrices(graph, demands, R_ij):
    """ 
    Solves the constrained optimization problem to find flows and unknown prices.
    
    --Outputs--
    graph (nx.MultiGraph): Returns the final graph with updated prices after all the routes.
    solution (dict): Returns the dict of solved variables
    """
    solver = Optimize()
    solver.set(timeout=30000) # 20 seconds timeout
    # Add variables 
    graph, f_R_vars = addVarsForSolver(graph, R_ij)
    # The graph.edges now has price vars (if price was null) and flow vars (f_e) added to each edge.

    # C1: Edge flow definition: Sum_R_flow_R = f_e for all e in E
    # Iterate over all edges in the graph
    for u, v, key, data in graph.edges(keys=True, data=True):
        f_e = data['f_e']
        price_var = data['price']
        # control price for efficient Solve Space 
        solver.add(price_var >= 5)
        solver.add(price_var <= 120)
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
        
    T_i_vars = [] 
    TOLERANCE_FLOW = 1
    TOLERANCE_COST = 5
    T_MAX = 
    T_MIN = 
    
    for i, demand in enumerate(demands):
        # 1. C3: Demand conservation
        d_i = demand["d"]
        f_R_sum = Sum(f_R_vars[i])
        solver.add(f_R_sum == d_i)
        
        # 2. Define the minimum cost variable T_i for this demand group
        T_i = Real(f"T_{i}") 
        T_i_vars.append(T_i)
        
        # Add bounds for T_i (efficiency)
        solver.add(T_i >= 0)
        solver.add(T_i <= 100) 

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
            # We use Implies (A => B) which is equivalent to NOT A OR B.
            
            # Use a small tolerance for "strictly positive" (e.g., 0.001) for Implies
            # solver.add(Implies(
            #     f_R >= TOLERANCE_FLOW,
            #     And(cost_R <= T_i + TOLERANCE_COST, cost_R >= T_i - TOLERANCE_COST)
            # ))
            solver.add(And(cost_R <= T_i + TOLERANCE_COST, cost_R >= T_i - TOLERANCE_COST))
        
    #  Add Non-negativity Constraint for all route flows (f_R)
    for f_R_list in f_R_vars:
        for f_R in f_R_list:
            solver.add(f_R >= 0)

    # Add Objective Function
    objective = getObjectiveExpr(graph, R_ij, f_R_vars)
    h = solver.minimize(objective)
    # --- Check SAT and return Updated graph, Solution set ---
    if solver.check() == sat:
        model = solver.model()
        
        # 1. Prepare solution dict
        solution = {}
        solution["R_ij"] = R_ij
        
        # Retrieve f_R values and convert to long
        f_R_vals = [[model.evaluate(f_R).as_long() for f_R in f_R_list] for f_R_list in f_R_vars]
        solution["f_R_vals"] = f_R_vals
        solution["objective_val"] = h.value()
        
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
        solution["solved_vars"] = {str(d): model[d] for d in model}
        
        return graph, solution
    else:
        print("Failed to solve for unknown prices.")
        return graph, None
        
    

def dynamicPricing(inputGraph, routesAdded, resultsFile):
    """ 
    Dynamic Pricing of Upcoming Lines.
    --Inputs--
    inputGraph (JSON file): Data to create the network and demands. see data/example.json
    routesAdded (JSON file): Ordered List of Rotes added to the network. see data/exampleRoutes.json
    resultsFile : Name of file to write results of experiments to. 
    """

    # Parse the input graph to create a networkx MultiGraph and demands
    graph, demands = parseGraph(inputGraph)

    # Parse the routesAdded JSON file 
    routes = parseRoutes(routesAdded)

    for route in routes:
        # Update the graph with new edges
        u, v, attr = route
        graph.add_edge(u, v, **attr)
        # Get Available Routes for each demand
        R_ij = getAllPossibleRoutes(graph, demands) 
        # Recalculate prices 
        graph, solution =  solveUnknownPrices(graph, demands, R_ij)
        if solution is not None:
            runExperiments(graph, solution, resultsFile)
    
    # append the final graph to the results file. 
    writeGraphToJSON(graph, resultsFile)
    pass



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A tool to set Dynamic Pricing of Upcoming Routes",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'inputGraph',
        type=str,
        help='file path of input JSON file'
    )
    parser.add_argument(
        'routesAdded',
        type=str,
        help='file path of routesAdded JSON file'
    )
    parser.add_argument(
        'resultsFile',
        type=str,
        help='file path of where to results to'
    )
    args = parser.parse_args()

    # run the tool
    dynamicPricing(args.inputGraph, args.routesAdded, args.resultsFile)


