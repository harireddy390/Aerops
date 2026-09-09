/**
 * AeroOps browser reporter — drop-in, zero dependencies.
 *
 * Catches window errors + unhandled promise rejections and reports them to
 * AeroOps, which turns them into incidents with stack forensics.
 *
 * Usage (plain JS or any framework):
 *   <script src="/aeroops-reporter.js"></script>
 *   <script>
 *     AeroOpsReporter.init({ endpoint: 'http://localhost:8000/api/telemetry/crash', service: 'my-web-app' });
 *   </script>
 *
 * React apps: also wrap your tree in AeroErrorBoundary (see AeroErrorBoundary.tsx).
 */
(function (global) {
  'use strict';

  var installed = false;
  var cfg = { endpoint: '', service: 'browser-app', release: '' };
  var lastSent = {}; // signature -> timestamp (client-side flood guard)

  function signature(p) {
    return (p.message || '') + '|' + (p.file || '') + ':' + (p.line || 0);
  }

  function send(payload) {
    var key = signature(payload);
    var now = Date.now();
    if (lastSent[key] && now - lastSent[key] < 60000) return; // max 1/min per unique crash
    lastSent[key] = now;
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: 'application/json' });
        if (navigator.sendBeacon(cfg.endpoint, blob)) return;
      }
    } catch (e) { /* fall through to fetch */ }
    try {
      fetch(cfg.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body,
        keepalive: true,
      }).catch(function () {});
    } catch (e) { /* telemetry must never break the host app */ }
  }

  function base() {
    return {
      service: cfg.service,
      release: cfg.release || '',
      url: String(location.href).slice(0, 500),
      userAgent: String(navigator.userAgent || '').slice(0, 300),
      occurredAt: new Date().toISOString(),
    };
  }

  function fromErrorEvent(msg, src, line, col, err) {
    var p = base();
    p.kind = 'onerror';
    p.message = String(msg || (err && err.message) || 'Unknown error').slice(0, 1000);
    p.file = String(src || '').slice(0, 500);
    p.line = Number(line) || 0;
    p.column = Number(col) || 0;
    p.stack = String((err && err.stack) || '').slice(0, 8000);
    send(p);
  }

  function fromRejection(ev) {
    var reason = ev && ev.reason;
    var p = base();
    p.kind = 'unhandledrejection';
    p.message = String((reason && (reason.message || reason)) || 'Unhandled rejection').slice(0, 1000);
    p.stack = String((reason && reason.stack) || '').slice(0, 8000);
    var m = p.stack.match(/\(?(https?:\/\/[^()\s]+):(\d+):(\d+)\)?/);
    p.file = m ? m[1].slice(0, 500) : '';
    p.line = m ? Number(m[2]) : 0;
    p.column = m ? Number(m[3]) : 0;
    send(p);
  }

  /** Report a React Error Boundary catch (or any manual report). */
  function report(error, info) {
    var p = base();
    p.kind = 'error-boundary';
    p.message = String((error && error.message) || error || 'Render error').slice(0, 1000);
    p.stack = String((error && error.stack) || '').slice(0, 8000);
    if (info && info.componentStack) p.componentStack = String(info.componentStack).slice(0, 4000);
    var m = p.stack.match(/\(?(https?:\/\/[^()\s]+):(\d+):(\d+)\)?/);
    p.file = m ? m[1].slice(0, 500) : '';
    p.line = m ? Number(m[2]) : 0;
    p.column = m ? Number(m[3]) : 0;
    send(p);
  }

  function init(options) {
    if (installed) return;
    options = options || {};
    if (!options.endpoint || !options.service) {
      throw new Error('AeroOpsReporter.init needs { endpoint, service }');
    }
    cfg.endpoint = options.endpoint;
    cfg.service = String(options.service).slice(0, 120);
    cfg.release = String(options.release || '').slice(0, 60);
    global.addEventListener('error', function (e) {
      try { fromErrorEvent(e.message, e.filename, e.lineno, e.colno, e.error); } catch (_) {}
    });
    global.addEventListener('unhandledrejection', function (e) {
      try { fromRejection(e); } catch (_) {}
    });
    installed = true;
  }

  global.AeroOpsReporter = { init: init, report: report };
})(typeof window !== 'undefined' ? window : this);
