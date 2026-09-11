/**
 * AeroOps live telemetry SDK — zero dependencies, ~3KB.
 *
 * Captures window errors + unhandled promise rejections from published web
 * apps (Lovable, React/Vite, any SPA) and beacons them to AeroOps, which
 * turns them into incidents and autonomously patches the linked repo.
 *
 * Embed (1-click snippet from the AeroOps service page):
 *   <script src="https://your-aeroops-host/sdk/aeroops.js"
 *           data-service-id="my-web-app"
 *           data-api-key="..."></script>
 *
 * Or manual init:
 *   <script src="https://your-aeroops-host/sdk/aeroops.js"></script>
 *   <script>
 *     AeroOps.init({
 *       serviceId: 'my-web-app',                       // id, name, or client_api_key
 *       endpoint: 'https://your-aeroops-host/api/telemetry/client',
 *       apiKey: '...',                                 // optional if serviceId is the key
 *       release: '1.4.2'                               // optional
 *     });
 *   </script>
 *
 * React — forward Error Boundary catches (or any manual report):
 *   try { ... } catch (err) { AeroOps.report(err, { componentStack: info.componentStack }); }
 *   // or: window.dispatchEvent(new CustomEvent('aeroops:report', { detail: { error, info } }))
 *   // See client-reporter/AeroErrorBoundary.tsx for a drop-in boundary.
 */
(function (global) {
  'use strict';

  var installed = false;
  var cfg = { serviceId: '', endpoint: '', apiKey: '', release: '' };

  // Flood guards: identical crashes max 1/min; global ceiling 10/min so a
  // render-loop cascade can never DDoS the ingest endpoint. Server enforces
  // its own sliding window on top (429 + Retry-After).
  var lastSent = {};
  var windowStart = 0;
  var windowCount = 0;

  function signature(p) {
    return (p.message || '') + '|' + (p.file_path || '') + ':' + (p.line_number || 0);
  }

  function send(payload) {
    var now = Date.now();
    var key = signature(payload);
    if (lastSent[key] && now - lastSent[key] < 60000) return;
    if (now - windowStart > 60000) { windowStart = now; windowCount = 0; }
    if (windowCount >= 10) return;
    lastSent[key] = now;
    windowCount += 1;
    var body = JSON.stringify(payload);
    var headers = { 'Content-Type': 'application/json' };
    if (cfg.apiKey) headers['X-AeroOps-Key'] = cfg.apiKey;
    try {
      // sendBeacon cannot set headers: the key already rides in the body.
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: 'application/json' });
        if (navigator.sendBeacon(cfg.endpoint, blob)) return;
      }
    } catch (e) { /* fall through to fetch */ }
    try {
      fetch(cfg.endpoint, {
        method: 'POST',
        headers: headers,
        body: body,
        keepalive: true,
      }).catch(function () {});
    } catch (e) { /* telemetry must never break the host app */ }
  }

  function base() {
    var href = '';
    var route = '';
    try {
      href = String(location.href).slice(0, 500);
      route = String(location.pathname + location.search).slice(0, 300);
    } catch (e) {}
    var ua = '';
    try { ua = String(navigator.userAgent || '').slice(0, 300); } catch (e) {}
    return {
      serviceId: cfg.serviceId,
      apiKey: cfg.apiKey || undefined,
      release: cfg.release || '',
      url: href,
      route: route,
      userAgent: ua,
      timestamp: new Date().toISOString(),
    };
  }

  function fromErrorEvent(msg, src, line, col, err) {
    var p = base();
    p.message = String(msg || (err && err.message) || 'Unknown error').slice(0, 2000);
    p.error_name = (err && err.name) || 'Error';
    p.file_path = String(src || '').slice(0, 1000);
    p.line_number = Number(line) || 0;
    p.column_number = Number(col) || 0;
    p.stack_trace = String((err && err.stack) || '').slice(0, 20000);
    send(p);
  }

  function fromRejection(ev) {
    var reason = ev && ev.reason;
    var p = base();
    var msg = (reason && (reason.message || reason)) || 'Unhandled rejection';
    p.message = String(msg).slice(0, 2000);
    p.error_name = (reason && reason.name) || 'UnhandledRejection';
    p.stack_trace = String((reason && reason.stack) || '').slice(0, 20000);
    var m = p.stack_trace.match(/\(?(https?:\/\/[^()\s]+):(\d+):(\d+)\)?/);
    p.file_path = m ? m[1].slice(0, 1000) : '';
    p.line_number = m ? Number(m[2]) : 0;
    p.column_number = m ? Number(m[3]) : 0;
    send(p);
  }

  /** Forward a React Error Boundary catch (or any manual report). */
  function report(error, info) {
    var p = base();
    p.message = String((error && error.message) || error || 'Render error').slice(0, 2000);
    p.error_name = (error && error.name) || 'Error';
    p.stack_trace = String((error && error.stack) || '').slice(0, 20000);
    if (info && info.componentStack) {
      p.componentStack = String(info.componentStack).slice(0, 8000);
    }
    var m = p.stack_trace.match(/\(?(https?:\/\/[^()\s]+):(\d+):(\d+)\)?/);
    p.file_path = m ? m[1].slice(0, 1000) : '';
    p.line_number = m ? Number(m[2]) : 0;
    p.column_number = m ? Number(m[3]) : 0;
    send(p);
  }

  function init(options) {
    if (installed) return;
    options = options || {};
    var serviceId = options.serviceId || options.service_id || options.service || '';
    var endpoint = options.endpoint || '';
    if (!serviceId || !endpoint) {
      throw new Error('AeroOps.init needs { serviceId, endpoint }');
    }
    cfg.serviceId = String(serviceId).slice(0, 120);
    cfg.endpoint = String(endpoint);
    cfg.apiKey = String(options.apiKey || options.api_key || options.client_api_key || '').slice(0, 64);
    cfg.release = String(options.release || options.version || '').slice(0, 60);
    global.addEventListener('error', function (e) {
      try { fromErrorEvent(e.message, e.filename, e.lineno, e.colno, e.error); } catch (_) {}
    });
    global.addEventListener('unhandledrejection', function (e) {
      try { fromRejection(e); } catch (_) {}
    });
    global.addEventListener('aeroops:report', function (e) {
      try {
        var d = (e && e.detail) || {};
        report(d.error, d.info);
      } catch (_) {}
    });
    installed = true;
  }

  function autoInit() {
    try {
      var scripts = document.getElementsByTagName('script');
      for (var i = 0; i < scripts.length; i++) {
        var s = scripts[i];
        var sid = s.getAttribute && s.getAttribute('data-service-id');
        if (sid && !installed) {
          init({
            serviceId: sid,
            apiKey: s.getAttribute('data-api-key') || '',
            release: s.getAttribute('data-release') || '',
            endpoint: s.getAttribute('data-endpoint') || defaultEndpoint(s),
          });
          return;
        }
      }
    } catch (e) {}
  }

  function defaultEndpoint(scriptEl) {
    try {
      var src = scriptEl.getAttribute('src') || '';
      var m = src.match(/^(https?:\/\/[^/]+)/);
      if (m) return m[1] + '/api/telemetry/client';
    } catch (e) {}
    return '/api/telemetry/client';
  }

  global.AeroOps = { init: init, report: report };
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', autoInit);
    } else {
      autoInit();
    }
  }
})(typeof window !== 'undefined' ? window : this);
