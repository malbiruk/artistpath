import React, { useRef, useEffect } from "react";
import * as d3 from "d3";

function NetworkVisualization({ data }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!data || !data.nodes || !data.edges) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const nodes = data.nodes.map((d) => ({ ...d }));
    const links = data.edges.map((d) => ({ ...d }));

    const containerRect = svgRef.current.getBoundingClientRect();
    const width = containerRect.width;
    const height = containerRect.height;

    svg
      .attr("width", width)
      .attr("height", height)
      .style("shape-rendering", "crispEdges");

    // Create node map for D3 linking
    const nodeMap = new Map();
    nodes.forEach((node) => {
      nodeMap.set(node.id, node);
    });

    // Convert string IDs to node objects for D3 (your API uses from/to)
    const validLinks = links.filter((link) => {
      const sourceNode = nodeMap.get(link.from);
      const targetNode = nodeMap.get(link.to);
      if (sourceNode && targetNode) {
        link.source = sourceNode;
        link.target = targetNode;
        return true;
      }
      return false;
    });

    // Create force simulation with similarity-based distances
    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(validLinks)
          .id((d) => d.id)
          .distance((d) => {
            // Higher similarity = shorter distance
            // similarity 1.0 -> 30px, similarity 0.0 -> 200px
            return 30 + (1 - d.similarity) * 170;
          })
          .strength((d) => {
            // Higher similarity = stronger connection
            return d.similarity * 0.8;
          }),
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(40));

    // Create links
    const link = svg
      .selectAll("line")
      .data(validLinks)
      .enter()
      .append("line")
      .attr("stroke", "black")
      .attr("stroke-width", 1);

    // Create nodes (rectangles)
    const nodeGroup = svg
      .selectAll("g.node")
      .data(nodes)
      .enter()
      .append("g")
      .attr("class", "node");

    nodeGroup
      .append("rect")
      .attr("width", (d) => d.name.length * 7 + 6)
      .attr("height", 24)
      .attr("x", (d) => -(d.name.length * 7 + 6) / 2)
      .attr("y", -12)
      .attr("fill", "white")
      .attr("stroke", (d) => (d.layer === 0 ? "#0000cc" : "black"))
      .attr("stroke-width", 1);

    nodeGroup
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .style("font-family", "inherit")
      .style("font-size", "11px")
      .style("pointer-events", "none")
      .style("fill", (d) => (d.layer === 0 ? "#0000cc" : "black"))
      .text((d) => d.name);

    // Update positions on each simulation tick
    simulation.on("tick", () => {
      link
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);

      nodeGroup.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    // Clean up simulation when component unmounts
    return () => {
      simulation.stop();
    };
  }, [data]);

  return (
    <svg
      ref={svgRef}
      style={{
        width: "100%",
        height: "100%",
        border: "none",
      }}
    />
  );
}

export default NetworkVisualization;
