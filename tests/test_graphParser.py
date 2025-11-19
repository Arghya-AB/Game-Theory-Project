from src.graphParser import parseGraph, writeGraphToJSON, parseRoutes
import networkx as nx
import pytest
from pathlib import Path

def testParseGraph():
    try:
        graph, demands = parseGraph("data/example.json")
    except FileNotFoundError as e:
        raise
    edges_repr = []
    for line in nx.generate_edgelist(graph, data=True):
        edges_repr.append(str(line))
    assert edges_repr[0] == "A C {'color': 'red', 'capacity': 100, 'price': 5, 'k': 1}"
    assert edges_repr[1] == "A C {'color': 'Bus', 'capacity': 500, 'price': 5, 'k': 2}"
    assert str(demands[0]) == "{'s': 'A', 't': 'C', 'd': 120}"

def testWriteGraphToJSON(tmp_path: Path):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    output_path = output_dir / "example_written.json"
    try:
        graph, _ = parseGraph("data/example.json")
        writeGraphToJSON(graph, output_path)
        graph_read = parseGraph(output_path, includeDemands=False)
    except FileNotFoundError as e:
        raise
    edges_repr = []
    for line in nx.generate_edgelist(graph_read, data=True):
        edges_repr.append(line)
    assert edges_repr[0] == "A C {'color': 'red', 'capacity': 100, 'price': 5, 'k': 1}"

def testParseRoutes():
    try:
        new_routes = parseRoutes("data/exampleRouteExt.json")
    except FileNotFoundError as e:
        raise
    edges_repr = []   
    for line in nx.generate_edgelist(new_routes, data=True):
        edges_repr.append(line)
    assert edges_repr[0] == "A E {'k': 1, 'color': 'red', 'capacity': 80, 'price': None}"