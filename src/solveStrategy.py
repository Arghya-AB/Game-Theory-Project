"""Defines Solve Strategies for solving the feasibility problem"""

from solverUtils import *
from z3 import sat,unsat, is_expr
from enum import Enum
import logging

logger = logging.getLogger(__name__)

def optimizeObjective(graph, R_ij, f_R_vars, demands, solver):
    """ Vanilla Strategy : Optimize using z3 under constraints"""
    logger.info("Solving with Optimize strategy" )
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
        log_msg = "Unable to sat Constraints with Objective. Current assertion: \n " \
            + str(solver.sexpr())
        logger.debug(log_msg)
        solver.pop()
        return None, False 

def setPricesHighToLow(graph, R_ij, f_R_vars, demands, solver):
    """Set Prices high to low till sat or iteration over"""
    P_MIN = 5
    P_MAX = 120
    P_DELTA = 5
    
    p_current = P_MAX
    isSat = sat # Assumes 'sat' is imported from z3
    model = None
    # Track the price that actually generated the model
    last_sat_price = None 
    logger.info("Solving with high to low strategy" )

    # Since Vanilla failed lets try some hints for z3
    # first lets estimate the f_R when routes cost fully determined/ To cut solution space
    for i, routes in enumerate(R_ij):
        route_prices = []
        for j, route_edges in enumerate(routes):
            route_prices.append(compute_route_price(graph,route_edges))
        if any([is_expr(route_price)==True for route_price in route_prices]):
            continue
        else:
            total = sum(route_prices)
            # this is the total spend by all source-demand commuters
            # set f_R_vars for this demand to be proportional wrt total costs of all
            # basically if the new edge addition does not enable new routes why f_R should be a variable for it just calculate it directly.
            f_R_vars[i] = [(route_price / total) * demands[i]["d"] for route_price in route_prices]   
            
    # keep decreasing till sat assignment or p_min hit keep while condition is sat 
    # because before any assertion solver gives sat but we want the loop to run at least once
    while(isSat == sat and p_current >= P_MIN):
        logger.info(f"Trying Sat with Price: {str(p_current)}" )
        # make graph copy
        graph_copy = graph.copy()
        # Update copy with current testing price
        for u, v, data in graph_copy.edges(data=True):
            if 'price' in data and is_expr(data['price']):
                data['price'] = float(p_current)

        solver.push()
        addConstraints(graph_copy, R_ij, f_R_vars, demands, solver)
        # Add Objective Function
        objective = getObjectiveExpr(graph_copy, R_ij, f_R_vars)
        h = solver.minimize(objective)

        isSat = solver.check()
        if isSat == sat: 
            model = solver.model() 
            last_sat_price = float(p_current) # This is the one that worked.
            solver.pop()
            p_current -= P_DELTA
            continue  # check sat at a lower price
        else: # Unsat below this Price Point
            log_msg = f"Unable to sat Constraints with current Price {str(p_current)}:\n " \
                + str(solver.sexpr())
            logger.debug(log_msg)
            solver.pop()
            break

    # Check if we ever found a valid model
    if model is not None and last_sat_price is not None:
        # Update the graph with the LAST SUCCESSFUL price
        for u, v, key, data in graph.edges(keys=True, data=True):
            if "price" in data and is_expr(data["price"]):
                data["price"] = last_sat_price
        logger.info(f"Final optimal price found: {last_sat_price}")
        return model, True
    else:
        return model, False  

def setPricesHighToLowWO(graph, R_ij, f_R_vars, demands, solver):
    """Set Prices high to low till sat or iteration over without objective function"""
    P_MIN = 5
    P_MAX = 120
    P_DELTA = 5
    
    p_current = P_MAX
    isSat = sat # Assumes 'sat' is imported from z3
    model = None
    # Track the price that actually generated the model
    last_sat_price = None 
    logger.info("Solving with high to low w/o Objective strategy" )

    # keep decreasing till sat assignment or p_min hit keep while condition is sat 
    # because before any assertion solver gives sat but we want the loop to run at least once
    while(isSat == sat and p_current >= P_MIN):
        logger.info(f"Trying Sat with Price: {str(p_current)}" )
        # make graph copy
        graph_copy = graph.copy()
        # Update copy with current testing price
        for u, v, data in graph_copy.edges(data=True):
            if 'price' in data and is_expr(data['price']):
                data['price'] = float(p_current)

        solver.push()
        addC1C2Constraints(graph, R_ij, f_R_vars, solver)
        #  Add Non-negativity Constraint for all route flows (f_R)
        for f_R_list in f_R_vars:
            for f_R in f_R_list:
                solver.add(f_R >= 0)
        addSimpleC3C4(graph, R_ij,f_R_vars,demands,solver)

        isSat = solver.check()
        if isSat == sat: 
            model = solver.model() 
            last_sat_price = float(p_current) # This is the one that worked.
            solver.pop()
            p_current -= P_DELTA
            continue  # check sat at a lower price
        else: # Unsat below this Price Point
            log_msg = f"Unable to sat Constraints with current Price {str(p_current)}:\n " \
                + str(solver.sexpr())
            logger.debug(log_msg)
            solver.pop()
            break

    # Check if we ever found a valid model
    if model is not None and last_sat_price is not None:
        # Update the graph with the LAST SUCCESSFUL price
        for u, v, key, data in graph.edges(keys=True, data=True):
            if "price" in data and is_expr(data["price"]):
                data["price"] = last_sat_price
        logger.info(f"Final optimal price found: {last_sat_price}")
        return model, True
    else:
        return model, False 

class Strategy(Enum):
    OPTIMIZE = optimizeObjective
    HIGHTOLOW = setPricesHighToLow
    HIGHTOLOW_WO = setPricesHighToLowWO

def trySolvingFeasibility(strategy, graph, R_ij, f_R_vars, demands, solver) :
    """Try solving Feasibility using a some Strategy """
    model, isSolved = strategy(graph,R_ij, f_R_vars, demands, solver)
    return model, isSolved