"""Defines Solve Strategies for solving the feasibility problem"""

from solverUtils import *
from z3 import sat,unsat, is_expr
from math import floor
from enum import Enum
import logging

logger = logging.getLogger(__name__)

def optimizeObjective(graph, R_ij, f_R_vars, demands, solver):
    """ Vanilla Strategy : Optimize using z3 under constraints"""
    logger.debug("Solving with Optimize strategy" )
    model = None
    isSolved = False

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
        return model, isSolved 

def setPricesHighToLow(graph, R_ij, f_R_vars, demands, solver, with_obj=False):
    """Set Prices high to low till sat or iteration over"""
    P_MIN = 5
    P_MAX = 120
    P_DELTA = 5
    
    p_current = P_MAX
    isSat = sat # Assumes 'sat' is imported from z3
    model = None
    # Track the price that actually generated the model
    last_sat_price = None 
    logger.debug("Solving with high to low strategy" )

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
        logger.debug(f"Trying Sat with Price: {str(p_current)}" )
        # make graph copy
        graph_copy = graph.copy()
        # Update copy with current testing price
        for u, v, data in graph_copy.edges(data=True):
            if 'price' in data and is_expr(data['price']):
                data['price'] = float(p_current)

        solver.push()
        addConstraints(graph_copy, R_ij, f_R_vars, demands, solver)
        if with_obj:
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
            if "f_e" in data and is_expr(data["f_e"]):
                f_e = data["f_e"] 
                data["f_e"] = model.evaluate(f_e).as_decimal(5)
        logger.info(f"Final optimal price found: {last_sat_price}")
        return model, True
    else:
        return model, False  

def binarySearchCapacity(graph, R_ij, f_R_vars, demands, solver):
    """Set Minimal Capacity via Binary search that sat """
    C_MIN = 500
    C_MAX = 5000
    c_current = floor((C_MIN+C_MAX)/2)
    model = None
    count = 0
    while(count<6):
        c_current = floor((C_MIN+C_MAX)/2)
        for u, v, key, data in graph.edges(keys=True, data=True):
            data["capacity"] = c_current
            # if is_expr(data.get("price")):
            #     data["capacity"] = c_current
        model, isSolved = optimizeObjective(graph, R_ij, f_R_vars, demands, solver)
        if isSolved:
            count +=1
            C_MAX = c_current
        else:
            count +=1
            C_MIN = c_current
    if isSolved:
        logger.info(f"Satisfying Capacity of edge : {str(c_current)}")
    return model, isSolved

def increaseCapacity(graph, R_ij, f_R_vars, demands, solver):
    """increase all edges capacity till sat """
    C_Delta = 50
    model = None
    count = 0
    while(count<10):
        for u, v, key, data in graph.edges(keys=True, data=True):
                data["capacity"] += C_Delta
        model, isSolved = optimizeObjective(graph, R_ij, f_R_vars, demands, solver)
        if isSolved:
            count +=1
            break
        else:
            count +=1
    if isSolved:
        logger.info(f"Increased Capacity of edge by : {str(C_Delta*(count+1))}")
    return model, isSolved


def setPricesHighToLowWO(graph, R_ij, f_R_vars, demands, solver):
    model = None
    isSolved = False

    model,isSolved = setPricesHighToLow(graph, R_ij, f_R_vars, demands, solver, with_obj=True)
    return model,isSolved 
    

class Strategy(Enum):
    OPTIMIZE = optimizeObjective
    HIGHTOLOW = setPricesHighToLow
    HIGHTOLOW_WO = setPricesHighToLowWO
    BSCAPACITY = binarySearchCapacity
    INCCAPACITY = increaseCapacity

def trySolvingFeasibility(strategy, graph, R_ij, f_R_vars, demands, solver) :
    """Try solving Feasibility using a some Strategy """
    model, isSolved = strategy(graph,R_ij, f_R_vars, demands, solver)
    return model, isSolved