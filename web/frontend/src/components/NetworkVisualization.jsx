import React, { useRef, useEffect } from "react";
import * as d3 from "d3";

function NetworkVisualization({ data }) {
  const svgRef = useRef(null);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const sampleNodes = [
      { id: "1", name: "Taylor Swift" },
      { id: "2", name: "Ed Sheeran" },
      { id: "3", name: "Adele" },
    ];

    const sampleLinks = [
      { source: "1", target: "2" },
      { source: "2", target: "3" },
    ];

    const containerRect = svgRef.current.getBoundingClientRect();
    const width = containerRect.width;
    const height = containerRect.height;

    svg
      .attr("width", width)
      .attr("height", height)
      .style("shape-rendering", "crispEdges");

    const nodePositions = [];
    let currentX = 100;

    sampleNodes.forEach((d, i) => {
      nodePositions.push(Math.round(currentX));
      const rectWidth = d.name.length * 7 + 6;
      if (i < sampleNodes.length - 1) {
        currentX +=
          rectWidth / 2 + 60 + (sampleNodes[i + 1].name.length * 7 + 6) / 2;
      }
    });

    svg
      .selectAll("line")
      .data(sampleLinks)
      .enter()
      .append("line")
      .attr("x1", (d, i) => nodePositions[i])
      .attr("y1", 200)
      .attr("x2", (d, i) => nodePositions[i + 1])
      .attr("y2", 200)
      .attr("stroke", "black")
      .attr("stroke-width", 1);

    svg
      .selectAll("rect")
      .data(sampleNodes)
      .enter()
      .append("rect")
      .attr("width", (d) => d.name.length * 7 + 6)
      .attr("height", 24)
      .attr("x", (d, i) => {
        const centerX = nodePositions[i];
        const rectWidth = d.name.length * 7 + 6;
        return Math.round(centerX - rectWidth / 2);
      })
      .attr("y", 200 - 12)
      .attr("fill", "white")
      .attr("stroke", "black")
      .attr("stroke-width", 1);

    svg
      .selectAll("text")
      .data(sampleNodes)
      .enter()
      .append("text")
      .attr("x", (d, i) => nodePositions[i])
      .attr("y", 200)
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .style("font-family", "inherit")
      .style("font-size", "11px")
      .style("pointer-events", "none")
      .text((d) => d.name);
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
