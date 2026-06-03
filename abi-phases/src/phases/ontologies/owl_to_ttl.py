if __name__ == "__main__":
    import sys
    from rdflib import Graph, URIRef, Literal, Namespace
    from rdflib.namespace import RDF, RDFS, OWL, XSD, DCTERMS

    owl_file = sys.argv[1]
    ttl_file = owl_file.replace(".owl", ".ttl")

    graph = Graph()
    graph.parse(owl_file, format="xml")
    graph.serialize(ttl_file, format="turtle")