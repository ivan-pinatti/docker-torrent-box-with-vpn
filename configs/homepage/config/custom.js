(function () {
  var attempts = 0;

  function injectVersion() {
    if (document.getElementById('header-version')) return true;
    attempts++;

    var widgetsWrap = document.getElementById('widgets-wrap');
    var footer = document.getElementById('footer');
    if (!widgetsWrap || !footer) return false;

    var versionEl = footer.querySelector('#version');
    if (!versionEl) return false;

    var link = versionEl.querySelector('a');
    var version, href;
    href = 'https://github.com/gethomepage/homepage';

    if (link) {
      var match = (link.getAttribute('href') || '').match(/tag\/(v[\d.]+)/);
      version = match ? match[1] : link.textContent.trim().split(/\s/)[0];
    } else {
      var span = versionEl.querySelector('span');
      var raw = span ? span.textContent.trim() : versionEl.textContent.trim();
      version = raw.split(/\s/)[0];
    }

    if (!version) return false;

    var badge = document.createElement('a');
    badge.id = 'header-version';
    badge.href = href;
    badge.target = '_blank';
    badge.rel = 'noopener noreferrer';

    var line1 = document.createElement('span');
    line1.textContent = 'Homepage';
    var line2 = document.createElement('span');
    line2.textContent = version;
    badge.appendChild(line1);
    badge.appendChild(line2);

    var first = widgetsWrap.firstElementChild;
    if (first) {
      first.insertAdjacentElement('afterend', badge);
    } else {
      widgetsWrap.append(badge);
    }
    return true;
  }

  injectVersion();
  document.addEventListener('DOMContentLoaded', injectVersion);
  window.addEventListener('load', injectVersion);

  var iv = setInterval(function () {
    if (injectVersion()) clearInterval(iv);
    if (attempts > 60) clearInterval(iv);
  }, 500);
})();
