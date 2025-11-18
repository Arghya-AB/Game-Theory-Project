import json
import networkx as nx
import logging
from networkx.readwrite import json_graph
from z3 import is_expr 
import os


def parseGraph(
    inputfile: str, includeDemands=True
) -> tuple[nx.MultiGraph, list[tuple]] | nx.MultiGraph | FileNotFoundError:
    """Create a  networkx.multiGraph and a list of demands(source,target,demand) from a JSON file."""
    # read the JSON file
    try:
        with open(inputfile, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logging.error(f"Error: The file {inputfile} was not found.")
        raise
    edge_list = []
    # for every network in networks
    for network in data.get("networks"):
        # add edges to edge list
        edge_list.extend(network.get("edge_list"))
    # Make Multi grpah
    graph = nx.parse_edgelist(edge_list, create_using=nx.MultiGraph)
    # add k if not present in an edge
    for u ,v, edge_data in graph.edges(data=True):
        if not edge_data.get("k"):
            edge_data["k"] = data.get("k")[edge_data.get("color")]

    if includeDemands:
        # return graph and demands
        return graph, data.get("demands")
    else:
        # return graph
        return graph


def writeGraphToJSON(graph, outputfile):
    """ 
    Write the graph to a JSON file, replacing Z3 expressions in edge data with None. 
    Appends the graph data to the 'graphs' list in the file.
    """
    clean_graph = graph.copy() 
    def clean_attributes(data):
        """ Replaces Z3 expressions in the attribute dictionary with None. """
        for key, value in list(data.items()):
            if is_expr(value):
                data[key] = None
    for u, v, data in clean_graph.edges(data=True):
        clean_attributes(data)
    edge_list = []
    for line in nx.generate_edgelist(clean_graph, data=True):
        edge_list.extend([line])

    new_graph_data = {"networks":[{"name":"Combined", "edge_list": edge_list}]}
    # Use 'w' to create if it doesn't exist
    with open(outputfile, 'w') as f:
        json.dump(new_graph_data, f, indent=4)


def parseRoutes(routesAdded) -> FileNotFoundError| nx.MultiGraph:
    "read the JSON file and return the extension graph i.e the edges that are getting added"
    try:
        with open(routesAdded, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: The file {routesAdded} was not found.")
        raise
    new_routes = nx.parse_edgelist(data.get("edge_list"), create_using=nx.MultiGraph)
    
    return new_routes
