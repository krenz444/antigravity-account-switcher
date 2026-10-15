#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_icon.py - Generates high-resolution multi-size .ico and .png icons for Antigravity Switchboard."""

import math
import os
from PIL import Image, ImageDraw, ImageFilter

def create_app_icon():
    # Render at 1024x1024 for ultra-smooth antialiasing
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    center = size // 2
    radius = size * 0.44

    # 1. Outer Soft Glow
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rounded_rectangle(
        [center - radius - 16, center - radius - 16, center + radius + 16, center + radius + 16],
        radius=200,
        fill=(56, 189, 248, 70) # Sky blue glow
    )
    glow = glow.filter(ImageFilter.GaussianBlur(32))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # 2. Main Rounded Squircle Background (Deep Slate Gradient)
    base_rect = [center - radius, center - radius, center + radius, center + radius]
    draw.rounded_rectangle(base_rect, radius=180, fill=(15, 23, 42, 255)) # #0f172a

    # Subtle inner background gradient layer
    inner_pad = 20
    draw.rounded_rectangle(
        [center - radius + inner_pad, center - radius + inner_pad, center + radius - inner_pad, center + radius - inner_pad],
        radius=160,
        fill=(30, 41, 59, 255) # #1e293b
    )

    # 3. Outer Neon Border (Cyan to Emerald)
    draw.rounded_rectangle(
        base_rect,
        radius=180,
        outline=(56, 189, 248, 220), # #38bdf8
        width=12
    )

    # 4. Draw 3 Orbiting Account Nodes (Triad for the 3 accounts)
    orbit_r = radius * 0.65
    node_angles = [ -90, 30, 150 ] # 3 equidistant positions
    node_colors = [
        (16, 185, 129, 255),  # Emerald (#10b981) - Account 1
        (56, 189, 248, 255),  # Sky Blue (#38bdf8) - Account 2
        (168, 85, 247, 255),  # Purple (#a855f7) - Account 3
    ]

    # Draw faint orbit ring connecting them
    orbit_bbox = [center - orbit_r, center - orbit_r, center + orbit_r, center + orbit_r]
    draw.ellipse(orbit_bbox, outline=(51, 65, 85, 160), width=6)

    # Draw curved rotation arrows along the orbit
    # Arc 1: -60 to 0 deg
    draw.arc(orbit_bbox, start=-65, end=5, fill=(16, 185, 129, 220), width=12)
    # Arrow head near 10 deg
    rad1 = math.radians(10)
    ax1 = center + orbit_r * math.cos(rad1)
    ay1 = center + orbit_r * math.sin(rad1)
    draw.polygon([
        (ax1, ay1),
        (ax1 - 24, ay1 - 20),
        (ax1 - 6, ay1 - 32)
    ], fill=(16, 185, 129, 240))

    # Arc 2: 60 to 120 deg
    draw.arc(orbit_bbox, start=55, end=125, fill=(56, 189, 248, 220), width=12)
    # Arrow head near 130 deg
    rad2 = math.radians(130)
    ax2 = center + orbit_r * math.cos(rad2)
    ay2 = center + orbit_r * math.sin(rad2)
    draw.polygon([
        (ax2, ay2),
        (ax2 + 10, ay2 - 28),
        (ax2 + 30, ay2 - 12)
    ], fill=(56, 189, 248, 240))

    # Arc 3: 175 to 245 deg
    draw.arc(orbit_bbox, start=175, end=245, fill=(168, 85, 247, 220), width=12)
    # Arrow head near 250 deg
    rad3 = math.radians(250)
    ax3 = center + orbit_r * math.cos(rad3)
    ay3 = center + orbit_r * math.sin(rad3)
    draw.polygon([
        (ax3, ay3),
        (ax3 + 14, ay3 + 26),
        (ax3 - 10, ay3 + 30)
    ], fill=(168, 85, 247, 240))

    # Draw the 3 nodes
    for angle_deg, col in zip(node_angles, node_colors):
        rad = math.radians(angle_deg)
        nx = center + orbit_r * math.cos(rad)
        ny = center + orbit_r * math.sin(rad)
        nr = 36
        # Node outer glow
        draw.ellipse([nx - nr - 8, ny - nr - 8, nx + nr + 8, ny + nr + 8], fill=(col[0], col[1], col[2], 60))
        # Node body
        draw.ellipse([nx - nr, ny - nr, nx + nr, ny + nr], fill=col, outline=(248, 250, 252, 230), width=6)

    # 5. Center Emblem: Antigravity Floating Core ("A" Chevron / Levitation Diamond)
    core_w = 90
    core_h = 130
    cx, cy = center, center - 6

    # Draw glowing diamond / inverted delta
    diamond = [
        (cx, cy - core_h),           # Top apex
        (cx + core_w, cy + 10),      # Right wing
        (cx, cy + core_h * 0.75),    # Bottom tip
        (cx - core_w, cy + 10)       # Left wing
    ]
    draw.polygon(diamond, fill=(248, 250, 252, 245))

    # Inner cut out (stylized chevron crossbar)
    inner_cut = [
        (cx, cy - core_h * 0.4),
        (cx + core_w * 0.5, cy + 20),
        (cx, cy + core_h * 0.35),
        (cx - core_w * 0.5, cy + 20)
    ]
    draw.polygon(inner_cut, fill=(15, 23, 42, 255))

    # Central levitation core dot (Cyan glowing star)
    core_r = 18
    draw.ellipse([cx - core_r, cy + 4 - core_r, cx + core_r, cy + 4 + core_r], fill=(56, 189, 248, 255))

    # 6. Save as PNG and Multi-Resolution ICO
    script_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(script_dir, "app_icon.png")
    ico_path = os.path.join(script_dir, "app_icon.ico")

    # Save PNG
    img.resize((512, 512), Image.Resampling.LANCZOS).save(png_path, format="PNG")
    print(f"Saved PNG icon: {png_path}")

    # Generate multi-size icon: 256, 128, 64, 48, 32, 16
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ico_path, format="ICO", sizes=icon_sizes)
    print(f"Saved Multi-Size ICO icon: {ico_path}")

    return ico_path, png_path

if __name__ == "__main__":
    create_app_icon()
