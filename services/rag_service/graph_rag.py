"""
GraphRAG System for AIOps.
Maintains a Knowledge Graph of system infrastructure topology (Pods, Nodes, Services, DBs, Alerts)
and performs hybrid semantic + relationship traversal to enrich standard RAG context.
"""

import logging
import re
from typing import Dict, Any, List, Set, Tuple

logger = logging.getLogger("graph_rag")


class InfrastructureKnowledgeGraph:
    """
    In-memory representation of high-fidelity DevOps & Infrastructure Topology.
    Contains nodes (entities) and edges (dependencies, containment, runtimes).
    """

    def __init__(self):
        # Nodes: Entity name -> metadata (type, status, IP)
        self.nodes: Dict[str, Dict[str, Any]] = {}
        # Edges: Entity name -> List of Tuple (related_entity, relation_type)
        self.edges: Dict[str, List[Tuple[str, str]]] = {}

        self._initialize_graph()

    def _initialize_graph(self):
        """Seed the graph with the system topology from docs/architecture.md and incident logs."""
        # 1. Services
        self.add_node(
            "gateway-service", "Service", "active", "10.96.0.1", "API Gateway entrance"
        )
        self.add_node(
            "web-service",
            "Service",
            "active",
            "10.96.0.2",
            "Main Web application frontend",
        )
        self.add_node(
            "auth-service",
            "Service",
            "active",
            "10.96.0.3",
            "User Authentication service",
        )
        self.add_node(
            "db-service",
            "Service",
            "active",
            "10.96.0.4",
            "PostgreSQL database core service",
        )
        self.add_node(
            "cache-service", "Service", "active", "10.96.0.5", "Redis cache layer"
        )
        self.add_node(
            "prometheus",
            "Service",
            "active",
            "10.96.0.100",
            "Metrics collection and alerting stack",
        )

        # 2. Pods running under Services
        self.add_node(
            "gateway-pod-1",
            "Pod",
            "running",
            "172.17.0.5",
            "Container for gateway service",
        )
        self.add_node(
            "web-pod-1",
            "Pod",
            "degraded",
            "172.17.0.12",
            "Web app instance 1 - CPU Alerting",
        )
        self.add_node(
            "web-pod-2", "Pod", "running", "172.17.0.13", "Web app instance 2"
        )
        self.add_node(
            "auth-pod-1", "Pod", "running", "172.17.0.14", "Auth service instance"
        )
        self.add_node(
            "db-pod-0", "Pod", "running", "172.17.0.20", "PostgreSQL statefulset pod"
        )
        self.add_node(
            "cache-pod-0",
            "Pod",
            "overloaded",
            "172.17.0.25",
            "Redis memory overload pod",
        )

        # 3. Physical/Virtual Nodes
        self.add_node(
            "k8s-node-1", "Node", "healthy", "192.168.1.10", "Kubernetes worker node 1"
        )
        self.add_node(
            "k8s-node-2",
            "Node",
            "high_load",
            "192.168.1.11",
            "Kubernetes worker node 2 - CPU bound",
        )

        # 4. Define Relations
        # Pods belonging to Services
        self.add_edge("gateway-pod-1", "gateway-service", "belongs_to")
        self.add_edge("web-pod-1", "web-service", "belongs_to")
        self.add_edge("web-pod-2", "web-service", "belongs_to")
        self.add_edge("auth-pod-1", "auth-service", "belongs_to")
        self.add_edge("db-pod-0", "db-service", "belongs_to")
        self.add_edge("cache-pod-0", "cache-service", "belongs_to")

        # Pods scheduled on Nodes
        self.add_edge("gateway-pod-1", "k8s-node-1", "runs_on")
        self.add_edge("web-pod-1", "k8s-node-2", "runs_on")
        self.add_edge("web-pod-2", "k8s-node-1", "runs_on")
        self.add_edge("auth-pod-1", "k8s-node-1", "runs_on")
        self.add_edge("db-pod-0", "k8s-node-2", "runs_on")
        self.add_edge("cache-pod-0", "k8s-node-2", "runs_on")

        # Service to Service Dependencies
        self.add_edge("gateway-service", "web-service", "depends_on")
        self.add_edge("web-service", "auth-service", "depends_on")
        self.add_edge("web-service", "db-service", "depends_on")
        self.add_edge("web-service", "cache-service", "depends_on")
        self.add_edge("auth-service", "db-service", "depends_on")

        # Incident/Alert correlation nodes
        self.add_node(
            "INC-102",
            "Incident",
            "active",
            "N/A",
            "CPU utilization exceeds 95% on web-pod-1",
        )
        self.add_edge("INC-102", "web-pod-1", "affects")
        self.add_edge("INC-102", "prometheus", "reported_by")

    def add_node(self, name: str, node_type: str, status: str, ip: str, desc: str):
        self.nodes[name] = {
            "name": name,
            "type": node_type,
            "status": status,
            "ip": ip,
            "description": desc,
        }

    def add_edge(self, source: str, target: str, relation: str):
        if source not in self.edges:
            self.edges[source] = []
        self.edges[source].append((target, relation))

        # Add reverse link for traversal ease
        if target not in self.edges:
            self.edges[target] = []
        self.edges[target].append(
            (
                source,
                f"is_{relation}_of"
                if not relation.startswith("is_")
                else relation.replace("is_", ""),
            )
        )

    def find_related_subgraph(
        self, entities: List[str], max_depth: int = 2
    ) -> Dict[str, Any]:
        """
        Traverses relationships starting from target entities up to max_depth.
        Returns a dictionary of matched entities and their relationships.
        """
        visited_nodes: Set[str] = set()
        matched_edges: List[Dict[str, str]] = []

        queue = [(ent, 0) for ent in entities if ent in self.nodes]
        for ent, _ in queue:
            visited_nodes.add(ent)

        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            connected = self.edges.get(current, [])
            for neighbor, rel in connected:
                # Add relationship edge
                matched_edges.append(
                    {"source": current, "target": neighbor, "relation": rel}
                )
                if neighbor not in visited_nodes:
                    visited_nodes.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return {
            "nodes": [self.nodes[n] for n in visited_nodes],
            "relationships": matched_edges,
        }

    def extract_entities(self, query: str) -> List[str]:
        """Scans the query for known infrastructure entities in the topology."""
        found = []
        query_lower = query.lower()
        for node_name in self.nodes.keys():
            # Match word bounds or substring match
            pattern = rf"\b{re.escape(node_name.lower())}\b"
            if re.search(pattern, query_lower):
                found.append(node_name)
            elif node_name.lower().replace("-", " ") in query_lower:
                found.append(node_name)
        return found


class GraphRagService:
    """Combines traditional Vector RAG lookup with Infrastructure Graph context."""

    def __init__(self):
        self.graph = InfrastructureKnowledgeGraph()

    def enrich_retrieval_with_graph(
        self, query: str, vector_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Takes query and vector results, detects infra entities, extracts graph neighbors,
        and injects high-fidelity graph context at the top of RAG results.
        """
        entities = self.graph.extract_entities(query)
        if not entities:
            logger.info(
                "GraphRAG: No infra entities detected in query. Returning standard Vector RAG."
            )
            return vector_results

        logger.info(
            f"GraphRAG: Detected entities {entities} in query. Performing relationship traversal."
        )
        subgraph = self.graph.find_related_subgraph(entities, max_depth=2)

        # Format the Graph context nicely as a virtual document chunk

        # 1. Format Nodes
        node_lines = ["Infrastructure Entities Status:"]
        for node in subgraph["nodes"]:
            status_emoji = (
                "🟢"
                if node["status"] in ["active", "running", "healthy"]
                else "🔴"
                if node["status"] in ["overloaded", "degraded", "high_load"]
                else "🟡"
            )
            node_lines.append(
                f"- {status_emoji} [{node['type']}] {node['name']}: IP={node['ip']}, State={node['status']}, Details='{node['description']}'"
            )

        # 2. Format Relationships
        rel_lines = ["Infrastructure Topographical Relationships:"]
        # Filter duplicates in relationships
        seen_rels = set()
        for rel in subgraph["relationships"]:
            rel_key = tuple(sorted([rel["source"], rel["target"]])) + (rel["relation"],)
            if rel_key not in seen_rels:
                seen_rels.add(rel_key)
                rel_lines.append(
                    f"- {rel['source']} --({rel['relation']})--> {rel['target']}"
                )

        graph_text = "\n".join(
            [
                "=== [GRAPH-RAG ADVANCED TOPOLOGY CONTEXT] ===",
                "\n".join(node_lines),
                "",
                "\n".join(rel_lines),
                "===============================================",
            ]
        )

        graph_chunk = {
            "id": "graph-rag-topology-context",
            "text": graph_text,
            "source": "Infrastructure Knowledge Graph (topology.json)",
            "chunk_index": 0,
            "score": 1.0,  # Perfect score for direct topological relation
        }

        # Ingest the Graph Chunk at the top of results
        return [graph_chunk] + vector_results
