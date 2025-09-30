"""
Custom Plotly template for consistent, beautiful visualizations.
Based on one_light colorscheme with custom colors.
"""

import plotly.graph_objects as go
import plotly.io as pio


def setup_custom_template():
    """Creates and registers the custom 'one_light' template."""

    custom_template = go.layout.Template()

    # Set the background colors
    custom_template.layout.paper_bgcolor = "#fafafa"
    custom_template.layout.plot_bgcolor = "#fafafa"

    # Set the font for the title
    custom_template.layout.title.font.family = "Serif"
    custom_template.layout.title.font.size = 20

    custom_template.layout.hovermode = "closest"

    # Customize axis
    custom_template.layout.xaxis.showgrid = False
    custom_template.layout.xaxis.showline = True
    custom_template.layout.xaxis.linecolor = "#d0d0d0"
    custom_template.layout.xaxis.zerolinecolor = "#eaeaea"
    custom_template.layout.yaxis.showgrid = False
    custom_template.layout.yaxis.showline = True
    custom_template.layout.yaxis.linecolor = "#d0d0d0"
    custom_template.layout.yaxis.zerolinecolor = "#eaeaea"

    # Set default color for traces
    custom_template.layout.colorway = [
        "lightseagreen",
        "lightsalmon",
        "steelblue",
        "lightpink",
        "plum",
        "skyblue",
        "darkseagreen",
        "darkgray",
        "darksalmon",
        "mediumturquoise",
        "lightcoral",
        "palegreen",
        "orchid",
        "powderblue",
        "thistle",
        "lightslategray",
        "peachpuff",
        "mistyrose",
        "lavender",
        "aquamarine",
        "wheat",
        "paleturquoise",
        "sandybrown",
        "lightcyan",
        "lightpink",
        "khaki",
        "mediumaquamarine",
        "lemonchiffon",
        "pink",
        "palevioletred",
        "moccasin",
        "burlywood",
        "gainsboro",
        "rosybrown",
        "palegoldenrod",
    ]

    custom_template.layout.colorscale = {"sequential": "purpor", "diverging": "Tealrose_r"}

    custom_template.layout.coloraxis.colorbar.len = 0.75
    custom_template.layout.coloraxis.colorbar.thickness = 20

    # Font defaults
    custom_template.layout.font.family = "Arial, sans-serif"
    custom_template.layout.font.size = 12
    custom_template.layout.font.color = "#2a2a2a"

    # Legend styling
    custom_template.layout.legend.bgcolor = "rgba(255, 255, 255, 0.9)"
    custom_template.layout.legend.bordercolor = "#d0d0d0"
    custom_template.layout.legend.borderwidth = 1

    # Register the template
    pio.templates["one_light"] = custom_template

    # Set as default
    pio.templates.default = "one_light"

    return custom_template


# Auto-initialize when imported
setup_custom_template()
