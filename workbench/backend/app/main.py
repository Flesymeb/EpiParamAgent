from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

from app.api.routes import router

app = FastAPI(
    title="MetaAgent-Epi Workbench API",
    version="0.1.0",
    description="Thin file-backed API for screening/extraction workbench views.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>MetaAgent-Epi Workbench API</title>
            <style>
              :root {
                color-scheme: light;
                --bg: #f4f8ef;
                --panel: rgba(255,255,255,0.84);
                --line: #dfe8d7;
                --text: #1f2937;
                --muted: #5f6b63;
                --accent: #597844;
                --accent-soft: #e5efdb;
              }
              * { box-sizing: border-box; }
              body {
                margin: 0;
                font-family: "Segoe UI", system-ui, sans-serif;
                color: var(--text);
                background:
                  radial-gradient(circle at top left, rgba(126, 151, 83, 0.16), transparent 28%),
                  radial-gradient(circle at top right, rgba(176, 125, 76, 0.10), transparent 24%),
                  linear-gradient(180deg, #f8faf6, #eef4ea 55%, #f7f5ee);
              }
              main {
                min-height: 100vh;
                display: grid;
                place-items: center;
                padding: 32px;
              }
              .card {
                width: min(760px, 100%);
                border: 1px solid var(--line);
                border-radius: 28px;
                background: var(--panel);
                backdrop-filter: blur(10px);
                box-shadow: 0 18px 44px rgba(62, 84, 49, 0.08);
                padding: 28px;
              }
              .eyebrow {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;
                border-radius: 999px;
                background: var(--accent-soft);
                color: var(--accent);
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
              }
              h1 {
                margin: 18px 0 12px;
                font-size: clamp(32px, 4vw, 42px);
                line-height: 1.08;
              }
              p {
                margin: 0;
                color: var(--muted);
                line-height: 1.7;
              }
              .grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 14px;
                margin-top: 24px;
              }
              .tile {
                border: 1px solid var(--line);
                border-radius: 22px;
                background: rgba(255,255,255,0.72);
                padding: 16px;
              }
              .tile strong {
                display: block;
                margin-bottom: 6px;
              }
              .links {
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                margin-top: 24px;
              }
              a {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 12px 18px;
                border-radius: 999px;
                text-decoration: none;
                font-weight: 600;
              }
              .primary {
                background: var(--accent);
                color: white;
              }
              .secondary {
                border: 1px solid var(--line);
                background: white;
                color: var(--text);
              }
            </style>
          </head>
          <body>
            <main>
              <section class="card">
                <div class="eyebrow">MetaAgent-Epi · Workbench API</div>
                <h1>Backend is running correctly.</h1>
                <p>
                  This process serves the local read-only API for the React workbench.
                  If you want the full visual interface, start the frontend too.
                </p>
                <div class="grid">
                  <div class="tile">
                    <strong>API health</strong>
                    <span><code>/api/health</code></span>
                  </div>
                  <div class="tile">
                    <strong>Run summary</strong>
                    <span><code>/api/summary</code></span>
                  </div>
                  <div class="tile">
                    <strong>Interactive docs</strong>
                    <span><code>/docs</code></span>
                  </div>
                </div>
                <div class="links">
                  <a class="primary" href="/docs">Open API docs</a>
                  <a class="secondary" href="/api/summary">View summary JSON</a>
                </div>
              </section>
            </main>
          </body>
        </html>
        """
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


app.include_router(router)
