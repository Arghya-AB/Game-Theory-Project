import argparse
import logging
from experiment import runExperiments 
from graphParser import parseGraph, writeGraphToJSON, parseRoutes
from z3 import  sat, Optimize ,is_expr
from solverUtils import (getAllPossibleRoutes, addVarsForSolver, 
                        UpdateGraphAndGetSolution)
from solveStrategy import trySolvingFeasibility, Strategy
import networkx as nx

def solveUnknownPrices(graph, demands, R_ij) -> dict:
    """ 
    Solves the constrained optimization problem to find flows and unknown prices.
    
    --Outputs--
    solution (dict): Returns the dict of solved variables
    """
    solver = Optimize()
    solver.set(timeout=2000) # 2 seconds timeout
    # solver.set("random_seed", 42)# for repeatable results
    # Add variables 
    f_R_vars = addVarsForSolver(graph, R_ij)
    # The graph.edges now has price vars (if price was null) and flow vars (f_e) added to each edge.
    # Check SAT with Optmisation
    strategies = [Strategy.OPTIMIZE, Strategy.HIGHTOLOW, Strategy.HIGHTOLOW_WO]
    
    for strategy in strategies:
        model, isSolved = trySolvingFeasibility(strategy,
                                            graph,
                                            R_ij,
                                            f_R_vars,
                                            demands,
                                            solver)
        if isSolved:
            logger.info(f"Feasibility solved with {str(strategy)} Strategy")
            solution = UpdateGraphAndGetSolution(graph, model, f_R_vars)
            return solution
    
    if not isSolved:
        logger.info("Failed to solve for unknown prices.")
        return None

        

def dynamicPricing(inputGraph, routesAdded, resultsFile):
    """ 
    Dynamic Pricing of Upcoming Lines.
    --Inputs--
    inputGraph (JSON file): Data to create the network and demands. see data/example.json
    routesAdded (JSON file): Ordered List of Rotes added to the network. see data/exampleRoutes.json
    resultsFile : Name of file to write results of experiments to. 
    """
    PRICE_HIGH = 25 #if route can be priced by any of the fallback add a high ticket and proceed to next
    # Parse the input graph to create a networkx MultiGraph and demands
    graph, demands = parseGraph(inputGraph)
    logger.info("Graph parsed")
    # Parse the routesAdded JSON file 
    new_routes = parseRoutes(routesAdded)
    logger.info("Routes Parsed")

    for route in new_routes.edges(data=True):
        # Update the graph with new edges
        u, v, attr = route
        graph.add_edge(u, v, **attr)
        # Get Available Routes for each demand
        R_ij = getAllPossibleRoutes(graph, demands)
        logger.info(f"Calculated All Possible Routes for source Destination Pairs after adding {str(u)}-> {str(v)}") 
        # Recalculate prices 
        solution =  solveUnknownPrices(graph, demands, R_ij)
        if solution is not None:
            logger.info("Solved Unknown Prices for the Routes")
            # runExperiments(graph, solution, resultsFile)
        else:
            logger.info("Unknown Prices Not Solved Setting a high value: {}")
            for u, v, data in graph.edges(data=True):
                price_var = data['price']
                if is_expr(price_var):
                    data['price'] = PRICE_HIGH

    # append the final graph to the results file. 
    if solution is not None:
        writeGraphToJSON(graph, resultsFile)
        logger.info("Wrote final Graph ResultsFile")




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
    parser.add_argument(
        '--logging',
        type=str,
        default="info",
        help='logging level : info, warning, debug'
    )
    args = parser.parse_args()
    # Set up logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level = getattr(logging, args.logging.upper()))
    # run the tool
    dynamicPricing(args.inputGraph, args.routesAdded, args.resultsFile)


