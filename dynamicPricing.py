import argparse
from experiment import runExperiments 
from graphParser import parseGraph, writeGraphToJSON, parseRoutes
from z3 import  sat, Optimize 
from solverUtils import (getAllPossibleRoutes, addVarsForSolver, 
                        getUpdatedGraphAndSolution, trySolvingFeasibility, Strategy)
import networkx as nx



def solveUnknownPrices(graph, demands, R_ij):
    """ 
    Solves the constrained optimization problem to find flows and unknown prices.
    
    --Outputs--
    graph (nx.MultiGraph): Returns the final graph with updated prices after all the routes.
    solution (dict): Returns the dict of solved variables
    """
    solver = Optimize()
    solver.set(timeout=2000) # 20 seconds timeout
    # Add variables 
    graph, f_R_vars = addVarsForSolver(graph, R_ij)
    # The graph.edges now has price vars (if price was null) and flow vars (f_e) added to each edge.
    # Check SAT with Optmisation 
    model, isSolved = trySolvingFeasibility(Strategy.OPTIMIZE,
                                             graph,
                                             R_ij,
                                             f_R_vars,
                                             demands,
                                             solver)

    if isSolved:
        graph, solution = getUpdatedGraphAndSolution(graph, model)
    else:
         # Try Manual High to Low setting to see if matches
        model, isSolved = trySolvingFeasibility(Strategy.HIGHTOLOW,
                                                graph,
                                                R_ij,
                                                f_R_vars,
                                                demands,
                                                solver)
        if isSolved:
            graph, solution = getUpdatedGraphAndSolution(graph, model, f_R_vars)
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
        graph, R_ij = getAllPossibleRoutes(graph, demands) 
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


