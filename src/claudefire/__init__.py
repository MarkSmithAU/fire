"""Claudefire: a gently burning GPU fire along the bottom of the screen.

The fire is drawn by a fragment shader directly to the screen at the display's
native resolution (e.g. 3840x2160 on a 4K monitor), with no rescaling. Controls:

    Esc / Q   quit
    Space     pause / resume
    Up/Down   raise / lower the flame height
"""

import argparse
from array import array
import sys
import time

import moderngl
import pygame

VERTEX_SHADER = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

FIRE_SHADER = """
#version 330
uniform float u_time;
uniform vec2  u_res;
uniform float u_height;   // base flame height as a fraction of screen height
in vec2 v_uv;
out vec4 frag;

// --- hashing & noise -------------------------------------------------------
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

vec2 hash22(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.xx + p3.yz) * p3.zy);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);   // quintic fade
    float a = hash12(i);
    float b = hash12(i + vec2(1.0, 0.0));
    float c = hash12(i + vec2(0.0, 1.0));
    float d = hash12(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
    float sum = 0.0;
    float amp = 0.5;
    mat2 rot = mat2(0.8, -0.6, 0.6, 0.8);
    for (int i = 0; i < 6; i++) {
        sum += amp * vnoise(p);
        p = rot * p * 2.03 + vec2(17.1, 9.2);
        amp *= 0.5;
    }
    return sum;
}

// --- black-body-ish colour ramp: black -> deep red -> orange -> yellow -> white
vec3 fireColor(float h) {
    h = clamp(h, 0.0, 1.0);
    vec3 c;
    c.r = smoothstep(0.00, 0.45, h);
    c.g = smoothstep(0.25, 0.85, h) * 0.72;
    c.b = smoothstep(0.80, 1.00, h) * 0.45;
    c.r = pow(c.r, 0.8);
    return c * (0.55 + 0.6 * h);
}

// --- rising embers ---------------------------------------------------------
float embers(vec2 p, float t) {
    float acc = 0.0;
    for (int layer = 0; layer < 3; layer++) {
        float fl = float(layer);
        float scale = 28.0 + fl * 18.0;
        float speed = 0.10 + fl * 0.04;
        vec2 q = p * scale;
        q.y -= t * speed * scale;
        q.x += sin(q.y * 0.15 + fl * 2.0 + t * 0.7) * 0.6;   // drift side to side
        vec2 cell = floor(q);
        vec2 f = fract(q);
        float rnd = hash12(cell + fl * 31.7);
        if (rnd > 0.035) continue;                            // sparse
        vec2 c = 0.2 + 0.6 * hash22(cell + fl * 13.3);
        float d = length(f - c);
        float twinkle = 0.6 + 0.4 * sin(t * (6.0 + rnd * 40.0) + rnd * 100.0);
        acc += smoothstep(0.10, 0.0, d) * twinkle * (1.0 - fl * 0.25);
    }
    return acc;
}

void main() {
    vec2 frag_px = v_uv * u_res;
    float aspect = u_res.x / u_res.y;
    vec2 uv = v_uv;
    vec2 p = vec2(uv.x * aspect, uv.y);
    float t = u_time;

    // The fire line "breathes": its height varies slowly along x and over time.
    float breathe = fbm(vec2(p.x * 1.2, t * 0.12));
    float h = u_height * (0.75 + 0.6 * breathe);
    h *= 0.95 + 0.05 * sin(t * 0.6);

    // Turbulence scrolling upward, domain-warped so tongues curl and lick.
    vec2 q = vec2(p.x * 3.2, p.y * 2.2 - t * 0.85);
    vec2 warp = vec2(fbm(q * 0.7 + vec2(0.0, -t * 0.25)),
                     fbm(q * 0.7 + vec2(5.2, -t * 0.30)));
    float n = fbm(q + 1.6 * warp);

    // Fine detail layer for flickering edges.
    float detail = fbm(vec2(p.x * 9.0, p.y * 6.0 - t * 1.8));

    // Gradiated intensity: hottest at the base, fading with height.
    float y = uv.y / h;
    float heat = 1.0 - y;
    heat += (n - 0.5) * (0.9 + 0.9 * y);   // turbulence grows toward the tips
    heat += (detail - 0.5) * 0.35 * y;
    heat *= 1.0 + 0.25 * (n - 0.5);
    heat = clamp(heat, 0.0, 1.0);
    heat = pow(heat, 1.6) * 0.93;

    // Extra white-hot bed right at the bottom.
    heat = max(heat, smoothstep(0.035, 0.0, uv.y) * (0.7 + 0.25 * n));

    vec3 col = fireColor(heat);

    // Warm ambient glow lighting the air above the fire.
    float glow = exp(-uv.y / (h * 1.6)) * (0.18 + 0.06 * sin(t * 1.3 + p.x * 0.8));
    col += vec3(1.0, 0.35, 0.08) * glow * (1.0 - heat);

    // Embers rising from the flames, fading as they climb.
    float e = embers(p, t);
    float eFade = smoothstep(h * 2.8, h * 0.6, uv.y) * smoothstep(h * 0.2, h * 0.7, uv.y);
    col += vec3(1.0, 0.55, 0.18) * e * eFade * 1.6;

    // Soft vignette and dithering (prevents banding in dark gradients).
    vec2 vc = v_uv - 0.5;
    col *= 1.0 - 0.35 * dot(vc, vc);
    col += (hash12(frag_px + fract(t) * 100.0) - 0.5) / 255.0;

    // Gentle filmic tone map.
    col = col / (1.0 + col * 0.25);
    frag = vec4(pow(col, vec3(1.0 / 1.1)), 1.0);
}
"""

def _make_dpi_aware() -> None:
    """Stop Windows display scaling from shrinking the reported resolution."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Gently burning fire demo at native resolution")
    parser.add_argument("--windowed", action="store_true", help="run in a window instead of fullscreen")
    parser.add_argument("--borderless", action="store_true", help="borderless window covering the desktop (fullscreen windowed)")
    parser.add_argument("--size", default="1920x1080", help="window size when --windowed (default 1920x1080)")
    parser.add_argument("--no-vsync", action="store_true", help="uncap frame rate (benchmark)")
    args = parser.parse_args()

    _make_dpi_aware()
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)

    flags = pygame.OPENGL | pygame.DOUBLEBUF
    if args.borderless:
        flags |= pygame.NOFRAME
        size = pygame.display.get_desktop_sizes()[0]
    elif args.windowed:
        w, h = (int(v) for v in args.size.lower().split("x"))
        size = (w, h)
    else:
        flags |= pygame.FULLSCREEN
        size = (0, 0)  # native desktop resolution
    surface = pygame.display.set_mode(size, flags, vsync=0 if args.no_vsync else 1)
    win_w, win_h = surface.get_size()
    pygame.display.set_caption("Claudefire")
    pygame.mouse.set_visible(args.windowed)

    ctx = moderngl.create_context()
    quad = ctx.buffer(array("f", [-1, -1, 1, -1, -1, 1, 1, 1]).tobytes())

    fire_prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FIRE_SHADER)
    fire_vao = ctx.vertex_array(fire_prog, [(quad, "2f", "in_pos")])

    fire_prog["u_res"].value = (win_w, win_h)
    flame_height = 0.24

    print(f"Rendering fire natively at {win_w}x{win_h}")
    print(f"GPU: {ctx.info['GL_RENDERER']}")

    start = time.perf_counter()
    paused_at = None
    frames, fps_timer = 0, start
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_SPACE:
                    if paused_at is None:
                        paused_at = time.perf_counter()
                    else:
                        start += time.perf_counter() - paused_at
                        paused_at = None
                elif event.key == pygame.K_UP:
                    flame_height = min(0.8, flame_height + 0.03)
                elif event.key == pygame.K_DOWN:
                    flame_height = max(0.08, flame_height - 0.03)

        now = time.perf_counter()
        t = (paused_at if paused_at is not None else now) - start

        ctx.screen.use()
        ctx.viewport = (0, 0, win_w, win_h)
        fire_prog["u_time"].value = t
        fire_prog["u_height"].value = flame_height
        fire_vao.render(moderngl.TRIANGLE_STRIP)

        pygame.display.flip()

        frames += 1
        if now - fps_timer >= 1.0:
            fps = frames / (now - fps_timer)
            pygame.display.set_caption(f"Claudefire - {win_w}x{win_h} @ {fps:.1f} fps")
            print(f"\r{fps:6.1f} fps", end="", flush=True)
            frames, fps_timer = 0, now

    print()
    pygame.quit()


if __name__ == "__main__":
    main()
