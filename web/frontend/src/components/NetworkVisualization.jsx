import React, { useRef, useEffect, useState } from "react";
import * as d3 from "d3";

function NetworkVisualization({
  data,
  onArtistClick,
  onClickAway,
  selectedArtistId,
}) {
  const svgRef = useRef(null);
  const onArtistClickRef = useRef(onArtistClick);
  const onClickAwayRef = useRef(onClickAway);

  // Update refs when props change
  useEffect(() => {
    onArtistClickRef.current = onArtistClick;
    onClickAwayRef.current = onClickAway;
  }, [onArtistClick, onClickAway]);

  useEffect(() => {
    if (!data || !data.nodes || !data.edges) return;

    // State for mobile interactions
    let activeNode = null;
    let activeEdge = null;
    let hoverTimeout = null;
    const isTouchDevice =
      "ontouchstart" in window || navigator.maxTouchPoints > 0;

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
      .style("shape-rendering", "geometricPrecision");

    const g = svg.append("g");

    // Calculate zoom extent based on node count
    const minZoom = Math.max(0.005, Math.min(0.5, 2 / Math.sqrt(nodes.length)));

    // Add zoom behavior
    const zoom = d3
      .zoom()
      .scaleExtent([minZoom, 3])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });

    svg.call(zoom);

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

    // Calculate connection count for each node
    const connectionCounts = new Map();
    nodes.forEach((node) => connectionCounts.set(node.id, 0));

    validLinks.forEach((link) => {
      connectionCounts.set(
        link.source.id,
        (connectionCounts.get(link.source.id) || 0) + 1,
      );
      connectionCounts.set(
        link.target.id,
        (connectionCounts.get(link.target.id) || 0) + 1,
      );
    });

    const maxConnections = Math.max(...connectionCounts.values());

    // Add connection count to nodes
    nodes.forEach((node) => {
      node.connectionCount = connectionCounts.get(node.id) || 0;
    });

    // Helper functions for repeated calculations
    const getNodeFontSize = (d) => {
      const baseFontSize = 9;
      const extraFontSize = 6;
      return (
        baseFontSize + (d.connectionCount / maxConnections) * extraFontSize
      );
    };

    const getNodeDimensions = (d) => {
      const fontSize = getNodeFontSize(d);
      const charWidth = fontSize * 0.6;
      const width = d.name.length * charWidth + 8;
      const height = fontSize + 10;
      return { width, height, fontSize };
    };

    const getNodeColor = (d) => {
      const isInPath =
        data.path && data.path.some((pathNode) => pathNode.id === d.id);
      return isInPath || d.layer === 0 ? "#0000cc" : "black";
    };

    const animateLink = (linkElement) => {
      linkElement
        .attr("stroke-dasharray", "5,5")
        .attr("stroke-dashoffset", 0)
        .transition()
        .duration(500)
        .ease(d3.easeLinear)
        .attr("stroke-dashoffset", -10)
        .on("end", function repeat() {
          linkElement
            .attr("stroke-dashoffset", 0)
            .transition()
            .duration(500)
            .ease(d3.easeLinear)
            .attr("stroke-dashoffset", -10)
            .on("end", repeat);
        });
    };

    const stopLinkAnimation = (linkElement) => {
      linkElement
        .interrupt()
        .attr("stroke-dasharray", null)
        .attr("stroke-dashoffset", null);
    };

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

    // Create links group
    const linkGroup = g.append("g").attr("class", "links");

    // Create visible links
    const link = linkGroup
      .selectAll("g.link")
      .data(validLinks)
      .enter()
      .append("g")
      .attr("class", "link");

    // Create path edge set for highlighting
    const pathEdges = new Set();
    if (data.path) {
      for (let i = 0; i < data.path.length - 1; i++) {
        const from = data.path[i].id;
        const to = data.path[i + 1].id;
        pathEdges.add(`${from}-${to}`);
        pathEdges.add(`${to}-${from}`); // Both directions
      }
    }

    // Visible line
    link
      .append("line")
      .attr("class", "link-line")
      .attr("stroke", (d) => {
        const edgeKey = `${d.source.id}-${d.target.id}`;
        return pathEdges.has(edgeKey) ? "#0000cc" : "black";
      })
      .attr("stroke-width", 1);

    // Invisible wider line for hover
    link
      .append("line")
      .attr("class", "link-hover")
      .attr("stroke", "transparent")
      .attr("stroke-width", 10)
      .style("cursor", "default")
      .on("mouseenter", function (event, d) {
        if (!isTouchDevice) {
          // Clear any pending timeout
          if (hoverTimeout) {
            clearTimeout(hoverTimeout);
            hoverTimeout = null;
          }

          // Create edge key for this connection (both directions)
          const edgeKey = [d.source.id, d.target.id].sort().join("-");

          // Only show if it's a different edge connection
          if (activeEdge !== edgeKey) {
            activeEdge = edgeKey;
            showEdgeTooltip(d);
          }
        }
      })
      .on("mouseleave", function (event, d) {
        if (!isTouchDevice) {
          // Debounce the mouseleave to prevent flickering
          if (hoverTimeout) clearTimeout(hoverTimeout);

          hoverTimeout = setTimeout(() => {
            const edgeKey = [d.source.id, d.target.id].sort().join("-");
            if (activeEdge === edgeKey) {
              activeEdge = null;
              clearEdgeTooltip();
            }
            hoverTimeout = null;
          }, 50);
        }
      })
      .on("click", function (event, clickedEdge) {
        event.stopPropagation();

        if (isTouchDevice) {
          // Clear any active node highlight
          clearNodeHighlight();

          // Toggle edge tooltip
          const edgeKey = `${clickedEdge.source.id}-${clickedEdge.target.id}`;
          if (activeEdge === edgeKey) {
            clearEdgeTooltip();
          } else {
            activeEdge = edgeKey;
            showEdgeTooltip(clickedEdge);
          }
        }
      });

    // Drag behavior for nodes
    function dragstarted(event, d) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }

    function dragged(event, d) {
      d.fx = event.x;
      d.fy = event.y;
    }

    function dragended(event, d) {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }

    // Create nodes (rectangles)
    const nodeGroup = g
      .selectAll("g.node")
      .data(nodes)
      .enter()
      .append("g")
      .attr("class", "node")
      .style("cursor", "pointer")
      .call(
        d3
          .drag()
          .on("start", dragstarted)
          .on("drag", dragged)
          .on("end", dragended),
      );

    // Helper functions for mobile interactions
    const clearNodeHighlight = () => {
      activeNode = null;
      nodeGroup.style("opacity", 1);
      link.style("opacity", 1);
      link.each(function () {
        stopLinkAnimation(d3.select(this).select(".link-line"));
      });
    };

    const clearEdgeTooltip = () => {
      activeEdge = null;
      g.selectAll(".edge-tooltip").remove();

      // Reset all opacities
      nodeGroup.style("opacity", 1);
      link.style("opacity", 1);

      // Stop all animations
      link.each(function () {
        stopLinkAnimation(d3.select(this).select(".link-line"));
      });
    };

    const showNodeConnections = (hoveredNode) => {
      // Find connected nodes
      const connectedNodes = new Set([hoveredNode.id]);
      validLinks.forEach((l) => {
        if (l.source.id === hoveredNode.id) connectedNodes.add(l.target.id);
        if (l.target.id === hoveredNode.id) connectedNodes.add(l.source.id);
      });

      // Gray out non-connected nodes
      nodeGroup.style("opacity", (d) => (connectedNodes.has(d.id) ? 1 : 0.2));

      // Gray out non-connected links
      link.style("opacity", (d) => {
        const isConnected =
          d.source.id === hoveredNode.id || d.target.id === hoveredNode.id;
        return isConnected ? 1 : 0.1;
      });

      // Animate connected edges
      link.each(function (d) {
        const isConnected =
          d.source.id === hoveredNode.id || d.target.id === hoveredNode.id;

        if (isConnected) {
          animateLink(d3.select(this).select(".link-line"));
        }
      });
    };

    const showEdgeTooltip = (d) => {
      // Clear existing tooltip
      g.selectAll(".edge-tooltip").remove();

      const thisLink = link
        .filter(
          (linkData) =>
            linkData.source.id === d.source.id &&
            linkData.target.id === d.target.id,
        )
        .select(".link-line");

      // Find maximum similarity between these two nodes (both directions)
      const allEdges = validLinks.filter(
        (linkData) =>
          (linkData.source.id === d.source.id &&
            linkData.target.id === d.target.id) ||
          (linkData.source.id === d.target.id &&
            linkData.target.id === d.source.id),
      );

      if (allEdges.length === 0) {
        console.warn("No edges found for tooltip", d);
        return;
      }

      const maxSimilarity = Math.max(
        ...allEdges.map((edge) => edge.similarity),
      );

      // Show max similarity score (strongest connection)
      const midX = (d.source.x + d.target.x) / 2;
      const midY = (d.source.y + d.target.y) / 2;

      const tooltip = g
        .append("g")
        .attr("class", "edge-tooltip")
        .attr("transform", `translate(${midX}, ${midY})`);

      tooltip
        .append("rect")
        .attr("x", -20)
        .attr("y", -10)
        .attr("width", 40)
        .attr("height", 20)
        .attr("fill", "white")
        .attr("stroke", "black")
        .style("pointer-events", "none");

      tooltip
        .append("text")
        .attr("text-anchor", "middle")
        .attr("dy", "0.35em")
        .style("font-size", "10px")
        .style("user-select", "none")
        .style("pointer-events", "none")
        .text(maxSimilarity.toFixed(2));

      // Gray out all other nodes and edges (focus on this connection)
      const connectedNodeIds = new Set([d.source.id, d.target.id]);

      nodeGroup.style("opacity", (node) =>
        connectedNodeIds.has(node.id) ? 1 : 0.2,
      );

      link.style("opacity", (linkData) => {
        const isThisConnection =
          (linkData.source.id === d.source.id &&
            linkData.target.id === d.target.id) ||
          (linkData.source.id === d.target.id &&
            linkData.target.id === d.source.id);
        return isThisConnection ? 1 : 0.1;
      });

      // Animate all links between these nodes (both directions)
      allEdges.forEach((edge) => {
        const linkToAnimate = link
          .filter(
            (linkData) =>
              linkData.source.id === edge.source.id &&
              linkData.target.id === edge.target.id,
          )
          .select(".link-line");

        if (!linkToAnimate.empty()) {
          animateLink(linkToAnimate);
        }
      });
    };

    // Add click-away handler for both mobile and desktop
    svg.on("click", function (event) {
      // Only handle if clicking on empty space (not nodes or edges)
      if (event.target === svgRef.current || event.target.tagName === "svg") {
        if (isTouchDevice) {
          clearNodeHighlight();
          clearEdgeTooltip();
        }

        // Close artist card on click away (desktop and mobile)
        if (onClickAwayRef.current) {
          onClickAwayRef.current();
        }
      }
    });

    nodeGroup
      .on("mouseenter", function (event, hoveredNode) {
        if (!isTouchDevice) {
          // Clear any active edge hover first
          if (activeEdge) {
            activeEdge = null;
            if (hoverTimeout) {
              clearTimeout(hoverTimeout);
              hoverTimeout = null;
            }
            clearEdgeTooltip();
          }
          showNodeConnections(hoveredNode);
        }
      })
      .on("mouseleave", function () {
        if (!isTouchDevice) {
          clearNodeHighlight();
        }
      })
      .on("click", function (event, clickedNode) {
        event.stopPropagation();

        if (isTouchDevice) {
          // Clear any active edge tooltip
          clearEdgeTooltip();

          // Double tap detection for mobile
          if (!clickedNode.tapCount) clickedNode.tapCount = 0;
          clickedNode.tapCount++;

          if (clickedNode.tapCount === 1) {
            // First tap - immediate single tap action
            if (activeNode === clickedNode.id) {
              clearNodeHighlight();
            } else {
              activeNode = clickedNode.id;
              showNodeConnections(clickedNode);
            }

            // Start timer to reset tap count
            clickedNode.tapTimer = setTimeout(() => {
              clickedNode.tapCount = 0;
            }, 300);
          } else if (clickedNode.tapCount === 2) {
            // Double tap - clear highlights and open artist card
            clearTimeout(clickedNode.tapTimer);
            clickedNode.tapCount = 0;
            clearNodeHighlight();
            if (onArtistClickRef.current) {
              onArtistClickRef.current(clickedNode);
            }
          }
        } else {
          // Desktop: open artist card on click
          if (onArtistClickRef.current) {
            onArtistClickRef.current(clickedNode);
          }
        }
      });

    nodeGroup
      .append("rect")
      .attr("width", (d) => getNodeDimensions(d).width)
      .attr("height", (d) => getNodeDimensions(d).height)
      .attr("x", (d) => -getNodeDimensions(d).width / 2)
      .attr("y", (d) => -getNodeDimensions(d).height / 2)
      .attr("fill", "white")
      .attr("stroke", getNodeColor)
      .attr("stroke-width", 1);

    nodeGroup
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .style("font-family", "inherit")
      .style("font-size", (d) => `${getNodeFontSize(d)}px`)
      .style("pointer-events", "none")
      .style("fill", getNodeColor)
      .text((d) => d.name);

    // Update positions on each simulation tick
    simulation.on("tick", () => {
      link
        .selectAll("line")
        .attr("x1", (d) => Math.round(d.source.x))
        .attr("y1", (d) => Math.round(d.source.y))
        .attr("x2", (d) => Math.round(d.target.x))
        .attr("y2", (d) => Math.round(d.target.y));

      nodeGroup.attr(
        "transform",
        (d) => `translate(${Math.round(d.x)},${Math.round(d.y)})`,
      );
    });

    // Clean up simulation when component unmounts
    return () => {
      simulation.stop();
    };
  }, [data]);

  // Separate effect just for updating selection styling
  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3.select(svgRef.current);
    const nodeGroups = svg.selectAll("g.node");

    // Update node rectangle colors
    nodeGroups
      .select("rect")
      .attr("fill", (d) => (d.id === selectedArtistId ? "black" : "white"));

    // Update text colors
    nodeGroups.select("text").style("fill", (d) => {
      if (d.id === selectedArtistId) return "white";
      const isInPath =
        data && data.path && data.path.some((pathNode) => pathNode.id === d.id);
      return isInPath || d.layer === 0 ? "#0000cc" : "black";
    });
  }, [selectedArtistId, data]);

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
