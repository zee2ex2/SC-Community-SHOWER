(function() {
  var params = new URLSearchParams(window.location.search);
  var urlTheme = params.get('theme');
  if (urlTheme) {
    document.documentElement.className = urlTheme;
    localStorage.setItem('theme', urlTheme);
    document.cookie = 'pref_theme=' + urlTheme + '; SameSite=Lax; Path=/; Max-Age=' + (86400 * 365);
  } else {
    var theme = localStorage.getItem('theme');
    if (theme) {
      document.documentElement.className = theme;
      document.cookie = 'pref_theme=' + theme + '; SameSite=Lax; Path=/; Max-Age=' + (86400 * 365);
    }
  }
})();

function setCookie(name, value, days) {
  document.cookie = name + '=' + value + '; SameSite=Lax; Path=/; Max-Age=' + (days * 86400);
}

function toggleTheme() {
  var html = document.documentElement;
  var theme = html.className === 'light' ? 'dark' : 'light';
  html.className = theme;
  localStorage.setItem('theme', theme);
  setCookie('pref_theme', theme, 365);
}

function setupAutocomplete(inputId, suggId, apiUrl) {
  var input = document.getElementById(inputId);
  var sugg = document.getElementById(suggId);
  var items = [];
  var sel = -1;

  function hide() { sugg.style.display = 'none'; sel = -1; }

  function fetch(q) {
    if (q.length < 1) { hide(); return; }
    var x = new XMLHttpRequest();
    x.open('GET', apiUrl + '?q=' + encodeURIComponent(q));
    x.onload = function() {
      items = JSON.parse(x.responseText);
      if (!items.length) { hide(); return; }
      sugg.innerHTML = items.map(function(n,i) { return '<div class="suggestion-item" data-idx="'+i+'">'+n+'</div>'; }).join('');
      sugg.style.display = 'block';
      sel = 0;
      var first = sugg.querySelector('.suggestion-item');
      if (first) first.classList.add('highlighted');
    };
    x.send();
  }

  function pick(i) {
    if (i >= 0 && i < items.length) {
      input.value = items[i];
      hide();
      var ev = new Event('input', {bubbles:true});
      input.dispatchEvent(ev);
    }
  }

  function highlight(i) {
    sugg.querySelectorAll('.suggestion-item').forEach(function(d,idx) {
      d.classList.toggle('highlighted', idx === i);
    });
    sel = i;
  }

  input.addEventListener('input', function() { fetch(this.value); });
  input.addEventListener('keydown', function(e) {
    if (sugg.style.display !== 'block' || !items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      highlight(sel === -1 ? 0 : Math.min(sel + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      highlight(sel === -1 ? 0 : Math.max(sel - 1, 0));
    } else if (e.key === 'Enter' && sel >= 0) {
      e.preventDefault();
      pick(sel);
    }
  });
  input.addEventListener('blur', function() {
    if (sel >= 0 && sel < items.length) pick(sel);
  });
  sugg.addEventListener('click', function(e) {
    var d = e.target.closest('.suggestion-item');
    if (d) pick(parseInt(d.dataset.idx));
  });
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.search-wrap')) hide();
  });
}

function toggleDropdown(e) {
  e.stopPropagation();
  document.getElementById('user-dropdown').classList.toggle('open');
}
document.addEventListener('click', function() {
  var dd = document.getElementById('user-dropdown');
  if (dd) dd.classList.remove('open');
});

var QTY_VALUES = (function() {
  var vals = [0];
  for (var v = 0.02; v <= 0.5; v = Math.round((v + 0.02) * 100) / 100) vals.push(v);
  for (var v = 0.6; v <= 1.5; v = Math.round((v + 0.1) * 100) / 100) vals.push(v);
  for (var v = 2; v <= 8; v = Math.round((v + 0.5) * 100) / 100) vals.push(v);
  return vals;
})();

function showFilter(name) {
  document.getElementById(name + "-overlay").style.display = "flex";
}

function hideFilter(name) {
  document.getElementById(name + "-overlay").style.display = "none";
}

function syncQual(event) {
  var el = event.target;
  var overlay = el.closest(".modal-overlay") || document;
  var minEl = overlay.querySelector("input[name='qual_min']");
  var maxEl = overlay.querySelector("input[name='qual_max']");
  if (!minEl || !maxEl) return;
  var minVal = parseInt(minEl.value);
  var maxVal = parseInt(maxEl.value);
  if (minVal > maxVal) {
    minEl.value = maxVal;
    minVal = maxVal;
  }
  var track = overlay.querySelector(".dual-slider");
  if (track) {
    track.style.setProperty("--min-pct", (minVal / 10) + "%");
    track.style.setProperty("--max-pct", (maxVal / 10) + "%");
  }
  overlay.querySelector("#qual-values").textContent = minVal + " \u2013 " + maxVal;
}

function syncQualFromStatic() {
  var overlay = document.getElementById("filter-overlay");
  if (!overlay) return;
  var minEl = overlay.querySelector("input[name='qual_min']");
  var maxEl = overlay.querySelector("input[name='qual_max']");
  if (!minEl || !maxEl) return;
  var minVal = parseInt(minEl.value);
  var maxVal = parseInt(maxEl.value);
  if (minVal > maxVal) { minEl.value = maxVal; minVal = maxVal; }
  var track = overlay.querySelector(".dual-slider");
  if (track) {
    track.style.setProperty("--min-pct", (minVal / 10) + "%");
    track.style.setProperty("--max-pct", (maxVal / 10) + "%");
  }
  overlay.querySelector("#qual-values").textContent = minVal + " \u2013 " + maxVal;
}

function updateQtyFilter(slider) {
  var idx = parseInt(slider.value);
  var scu = QTY_VALUES[idx];
  document.getElementById("qty-min-cents").value = scu.toFixed(2);
  var display = document.getElementById("qty-display");
  display.textContent = (idx === QTY_VALUES.length - 1) ? "8+ SCU" : scu.toFixed(2) + " SCU";
  var wrap = slider.closest(".qty-slider-wrap");
  if (wrap) wrap.style.setProperty("--qty-pct", (idx / (QTY_VALUES.length - 1)) * 100 + "%");
}

function initQtyFilter(scuStr) {
  var slider = document.getElementById("qty-slider");
  if (!slider) return;
  var scu = parseFloat(scuStr || 0);
  var closest = 0;
  for (var i = 0; i < QTY_VALUES.length; i++) {
    if (Math.abs(QTY_VALUES[i] - scu) < Math.abs(QTY_VALUES[closest] - scu)) closest = i;
  }
  slider.value = closest;
  var wrap = slider.closest(".qty-slider-wrap");
  if (wrap) wrap.style.setProperty("--qty-pct", (closest / (QTY_VALUES.length - 1)) * 100 + "%");
  updateQtyFilter(slider);
}

function copyKey(id) {
  var val = document.getElementById(id).textContent;
  navigator.clipboard.writeText(val).then(function() {
    var btn = document.querySelector('[data-for="' + id + '"]');
    btn.textContent = 'Copied!';
    setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
  });
}

function createKey() {
  var label = prompt('Label for this API key:', 'PITS sync key');
  if (!label) return;
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/keys/create');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.onload = function() {
    var resp = JSON.parse(xhr.responseText);
    if (resp.key) {
      var msg = document.getElementById('new-key-msg');
      msg.innerHTML = '<div class="message success">New API key: <code style="word-break:break-all">' + resp.key + '</code><br><small style="color:var(--muted)">Copy this now \u2014 it won\'t be shown again.</small></div>';
    }
  };
  xhr.send(JSON.stringify({label: label}));
}

function toggleSection(el) {
  var content = el.parentElement.querySelector('.collapse-content');
  var arrow = el.querySelector('.collapse-arrow');
  if (content.style.display === 'none') {
    content.style.display = 'block';
    arrow.innerHTML = '\u25BC';
  } else {
    content.style.display = 'none';
    arrow.innerHTML = '\u25B6';
  }
}

function editRole(id, name, level, discordRoleId) {
  document.getElementById('role-action').value = 'update_role';
  document.getElementById('role-id').value = id;
  document.getElementById('role-name').value = name;
  document.getElementById('role-modal-title').textContent = 'Edit Role';
  var radios = document.querySelectorAll('#role-form input[name="level"]');
  for (var i = 0; i < radios.length; i++) {
    radios[i].checked = parseInt(radios[i].value) === level;
  }
  var dridField = document.getElementById('role-discord-id');
  if (dridField) {
    if (dridField.tagName === 'SELECT') {
      for (var j = 0; j < dridField.options.length; j++) {
        if (dridField.options[j].value === discordRoleId) {
          dridField.selectedIndex = j;
          break;
        }
      }
    } else {
      dridField.value = discordRoleId || '';
    }
  }
  document.getElementById('role-overlay').style.display = 'flex';
}
