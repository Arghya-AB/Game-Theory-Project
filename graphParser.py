
import json
import networkx as nx
from networkx.readwrite import json_graph
from z3 import is_expr 
import os

def parseGraph(inputfile, includeDemands=True):
    """ Create a  networkx.multiGraph and a list of demands(source,target,demand) from a JSON file."""
    # read the JSON file
    try:
        with open(inputfile, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: The file {inputfile} was not found.")
        return None
    nodes = []
    edges = []
    # for every network in networks
    for network in data.get('networks'):
        #add nodes 
        nodes.extend(network.get("nodes"))
        # add edges with attributes
        for edge in network.get("edges"):
            # add k to edges from JSON root
            if "k" not in edge.get("data"):
                if network.get("name") == "Metro":
                    edge.get("data")["k"] = data.get("k")["Metro"][edge.get("data")["color"]]
                if network.get("name") == "Bus":
                    edge.get("data")["k"] = data.get("k")["Bus"]
            edges += [(edge.get("v1"), edge.get("v2"), edge.get("data"))]
    # Make Multi grpah 
    graph = nx.MultiGraph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from(edges)

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
    for u, v, key, data in clean_graph.edges(keys=True, data=True):
        clean_attributes(data)
    new_graph_data = json_graph.node_link_data(clean_graph,edges="edges")
    if os.path.exists(outputfile):
        with open(outputfile, 'r') as f:
            file_data = json.load(f)
        graphs_list = file_data.get('graphs')
        if isinstance(graphs_list, list):
            graphs_list.append(new_graph_data)
        else:
            file_data['graphs'] = [new_graph_data]
            
        with open(outputfile, 'w') as f:
            json.dump(file_data, f, indent=4)
    else:
        # File doesn't exist, create initial structure
        data = {
            "graphs": [new_graph_data]
        }
        # Use 'w' to create if it doesn't exist
        with open(outputfile, 'w') as f:
            json.dump(data, f, indent=4)


def parseRoutes(routesAdded):
    "read the JSON file and return the ordered list of edges added"
    try:
        with open(routesAdded, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: The file {routesAdded} was not found.")
        return None
    edges = []
    for edge in data.get('edges'):
        edges += [(edge.get("v1"), edge.get("v2"), edge.get("data"))]
    
    return edges
