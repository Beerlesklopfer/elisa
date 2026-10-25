// who-is-online: aktualisiert die Online-Punkte in ALLEN Chat-Systemen.
// Jede Teilnehmer-Leiste trägt data-online-url; wir pollen sie regelmäßig.
(function () {
  function refresh(strip) {
    fetch(strip.dataset.onlineUrl, { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.json(); })
      .then(function (map) {
        strip.querySelectorAll('.presence-dot').forEach(function (dot) {
          var on = !!map[dot.dataset.handle];
          dot.classList.toggle('on', on);
          dot.classList.toggle('off', !on);
        });
      })
      .catch(function () { /* offline/Netz – stillschweigend ignorieren */ });
  }
  function tick() {
    document.querySelectorAll('.chat-participants[data-online-url]').forEach(refresh);
  }
  document.addEventListener('DOMContentLoaded', tick);
  setInterval(tick, 30000);   // alle 30 s
})();
