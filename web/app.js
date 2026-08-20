const $ = (id) => document.getElementById(id);
const travelerQuery = new URLSearchParams(location.search).get('traveler');
let travelerId = travelerQuery || 'chengyu';
let travelerName = '程渝';
let companionName = '小小';

const EVENT_NAMES = {
  arrival: '抵达', resume: '继续旅程', look: '转身看看', move: '前往下一处',
  move_failed: '试探道路', moment: '留下片刻', reflection: '写下手记',
  postcard: '寄出明信片', departure: '结束旅程'
};

const QUOTE_NAMES = {
  arrival_quote: '落地第一句', observation_quote: '旅途原话', postcard: '明信片',
  travel_reflection: '私人手记', departure_quote: '离开前一句'
};

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

function number(value, suffix = '') {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1).replace(/\.0$/, '')}${suffix}` : '未知';
}

function dateTime(value, withDate = false) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', {
    month: withDate ? '2-digit' : undefined,
    day: withDate ? '2-digit' : undefined,
    hour: '2-digit', minute: '2-digit', hour12: false
  }).format(date);
}

function duration(startedAt, endAt) {
  const start = new Date(startedAt).getTime();
  const end = endAt ? new Date(endAt).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '未知';
  const minutes = Math.max(0, Math.floor((end - start) / 60000));
  if (minutes < 60) return `${minutes} 分钟`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
  return `${Math.floor(minutes / 1440)} 天 ${Math.floor(minutes % 1440 / 60)} 小时`;
}

function latestWordsEvent(events) {
  return [...events].reverse().find(event => event.event_type !== 'postcard');
}

function postcardImage(event) {
  const image = event?.metadata?.postcard_image;
  if (!image?.available || !image.image_url) return '';
  try {
    const url = new URL(image.image_url, location.href);
    const safePath = url.pathname.startsWith('/media/postcards/')
      || url.pathname.startsWith('/reality-travel/media/postcards/');
    if (url.origin !== location.origin || !safePath) return '';
    return url.href;
  } catch (_) {
    return '';
  }
}

function postcardCard(event) {
  const imageUrl = postcardImage(event);
  const artwork = imageUrl
    ? `<img src="${esc(imageUrl)}" alt="${esc(travelerName)}寄出的明信片正面">`
    : '<div class="travel-postcard-front-empty">POST CARD</div>';
  return `<article class="travel-postcard" data-event-id="${esc(event.event_id || '')}">
    <div class="travel-postcard-inner">
      <section class="travel-postcard-face travel-postcard-front">
        ${artwork}
        <div class="travel-postcard-front-band"><strong>POST CARD</strong><small>${esc(event.place_name || '旅途中')}</small></div>
        <button type="button" class="travel-postcard-turn" onclick="togglePostcard(this)">翻到背面</button>
      </section>
      <section class="travel-postcard-face travel-postcard-back">
        <div class="travel-postcard-copy">
          <div class="travel-postcard-kicker">POST CARD · FROM ${esc(travelerName)}</div>
          <p>${esc(event.quote_text || '')}</p>
        </div>
        <div class="travel-postcard-address">
          <div class="travel-postcard-stamp">K·PAX<br>TRAVEL</div>
          <span></span><span></span><span></span>
          <small>${esc(event.place_name || '旅途中')}<br>${esc(dateTime(event.occurred_at, true))}</small>
        </div>
        <button type="button" class="travel-postcard-turn" onclick="togglePostcard(this)">翻到正面</button>
      </section>
    </div>
  </article>`;
}

function togglePostcard(button) {
  const card = button?.closest?.('.travel-postcard');
  if (card) card.classList.toggle('is-flipped');
}

function renderHero(journey) {
  const street = journey?.street_view || {};
  const active = Boolean(journey);
  $('statusTag').className = `hero-tag ${active ? '' : 'idle'}`;
  $('statusTag').querySelector('b').textContent = active ? '旅途中' : '尚未出发';
  $('sceneUpdated').textContent = active ? dateTime(journey.last_activity_at, true) : '尚未出发';
  if (!active) {
    $('heroEmpty').hidden = false;
    $('heroImage').hidden = true;
    $('heroScrim').hidden = true;
    $('heroInfo').hidden = true;
    $('streetNote').textContent = '';
    return;
  }
  if (street.available && street.image_url) {
    $('heroImage').src = street.image_url;
    $('heroImage').hidden = false;
    $('heroEmpty').hidden = true;
    $('heroScrim').hidden = false;
    $('heroInfo').hidden = false;
    $('placeName').textContent = journey.place_name;
    $('sceneMeta').textContent = `朝向 ${number(journey.heading, '°')} · 街景拍摄 ${street.capture_date || '日期未提供'}`;
    $('streetNote').textContent = 'Google 历史街景，与当前天气分别记录。临时街景缓存过期后会安静隐藏。';
  } else {
    $('heroImage').hidden = true;
    $('heroScrim').hidden = true;
    $('heroInfo').hidden = true;
    $('heroEmpty').hidden = false;
    $('heroEmpty').innerHTML = `<i data-lucide="image-off"></i><strong>这里暂时没有街景</strong><p>${esc(street.message || `${travelerName}仍然知道自己在哪里，也可以继续行动和想象。`)}</p>`;
    $('streetNote').textContent = journey.place_name;
  }
}

function renderWeather(journey) {
  const weather = journey?.weather || {};
  $('weatherUpdated').textContent = weather.observed_at ? `当地 ${weather.observed_at}` : '';
  if (!journey || !weather.available) {
    $('weatherStrip').innerHTML = '<div class="weather-empty"><i data-lucide="cloud-off"></i><span>还没有环境资料</span></div>';
    return;
  }
  const elevation = journey.location?.elevation_m;
  $('weatherStrip').innerHTML = `
    <div class="weather-main">
      <span class="weather-temp">${esc(number(weather.temperature_c, '°'))}</span>
      <span class="weather-cond">${esc(weather.weather_text || '未知')}</span>
      <span class="weather-feel">体感 ${esc(number(weather.feels_like_c, '°'))}</span>
    </div>
    <div class="weather-pills">
      <span class="weather-pill">湿度 <b>${esc(number(weather.humidity_percent, '%'))}</b></span>
      <span class="weather-pill">风速 <b>${esc(number(weather.wind_kmh, ' km/h'))}</b></span>
      <span class="weather-pill">阵风 <b>${esc(number(weather.gust_kmh, ' km/h'))}</b></span>
      <span class="weather-pill">海拔 <b>${esc(number(elevation, ' m'))}</b></span>
    </div>`;
}

function renderWords(events) {
  const quote = latestWordsEvent(events);
  if (!quote?.quote_text) {
    $('wordsBubble').classList.remove('postcard-host');
    $('wordsBubble').innerHTML = '<div class="msg-empty"><i data-lucide="message-circle"></i><span>旅途中还没有留下原话</span></div>';
    return;
  }
  $('wordsBubble').classList.remove('postcard-host');
  $('wordsBubble').innerHTML = `
    <p class="msg-quote">${esc(quote.quote_text)}</p>
    <div class="msg-meta"><span>${esc(QUOTE_NAMES[quote.quote_kind] || '旅途原话')}</span><time>${esc(dateTime(quote.occurred_at, true))}</time></div>`;
}

function eventWeather(event) {
  const weather = event.weather || {};
  if (!weather.available) return '';
  return [weather.weather_text, number(weather.temperature_c, '℃'), `风 ${number(weather.wind_kmh, ' km/h')}`].filter(Boolean).join(' · ');
}

function timelineStreetView(event) {
  const street = event?.street_view || {};
  if (event?.event_type === 'postcard' || !street.available || !street.pano_id) return '';
  const endpoint = `api/events/${encodeURIComponent(event.event_id)}/streetview`;
  const capture = street.capture_date ? `拍摄于 ${street.capture_date} · ` : '';
  return `<details class="timeline-archive timeline-street" data-event-id="${esc(event.event_id || '')}" ontoggle="loadTimelineStreetView(this)">
    <summary><span>查看当时街景</span><small>${esc(capture)}Google Street View</small></summary>
    <div class="timeline-archive-body timeline-street-body">
      <div class="timeline-media-loading">点开后正在取回当时视角…</div>
      <img data-src="${esc(endpoint)}" alt="${esc(event.place_name || '旅途节点')}当时的 Google 街景">
      <p>${esc(street.copyright || '© Google')} · pano ${esc(street.pano_id)}</p>
    </div>
  </details>`;
}

function timelineQuote(event) {
  if (!event?.quote_text || event.quote_kind === 'postcard') return '';
  return `<details class="timeline-archive timeline-quote">
    <summary><span>${esc(travelerName)}当时说的话</span><small>${esc(QUOTE_NAMES[event.quote_kind] || '旅途原话')}</small></summary>
    <div class="timeline-archive-body"><p class="timeline-quote-text">${esc(event.quote_text)}</p></div>
  </details>`;
}

function timelinePostcard(event) {
  if (event?.quote_kind !== 'postcard') return '';
  return `<details class="timeline-archive timeline-postcard-archive">
    <summary><span>查看明信片</span><small>${esc(travelerName)}寄出</small></summary>
    <div class="timeline-archive-body">${postcardCard(event)}</div>
  </details>`;
}

function loadTimelineStreetView(details) {
  if (!details?.open) return;
  const image = details.querySelector('img[data-src]');
  if (!image || image.dataset.loaded === 'true') return;
  const loading = details.querySelector('.timeline-media-loading');
  image.onload = () => {
    image.dataset.loaded = 'true';
    image.classList.add('is-ready');
    if (loading) loading.hidden = true;
  };
  image.onerror = () => {
    image.removeAttribute('src');
    if (loading) loading.textContent = '这张历史街景暂时无法取回，可以稍后再试。';
  };
  image.src = image.dataset.src;
}

function updateTimelineCount() {
  const count = document.querySelectorAll('#timeline .tnode').length;
  $('eventCount').textContent = `${count} 个节点`;
}

function showTimelineUndo(eventId) {
  let toast = $('timelineUndo');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'timelineUndo';
    toast.className = 'timeline-undo';
    document.body.appendChild(toast);
  }
  toast.innerHTML = `<span>已从时间线隐藏，30 天后自动清理</span><button type="button">撤销</button>`;
  toast.classList.add('is-visible');
  toast.querySelector('button').onclick = () => restoreTimelineEvent(eventId);
  clearTimeout(window.timelineUndoTimer);
  window.timelineUndoTimer = setTimeout(() => toast.classList.remove('is-visible'), 8000);
}

async function hideTimelineEvent(button, eventId) {
  if (!eventId || button.disabled) return;
  button.disabled = true;
  try {
    const response = await fetch(`api/events/${encodeURIComponent(eventId)}`, {
      method: 'DELETE',
      headers: {'Accept': 'application/json'}
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    button.closest('.tnode')?.remove();
    updateTimelineCount();
    showTimelineUndo(eventId);
  } catch (_) {
    button.disabled = false;
    button.title = '隐藏失败，请稍后重试';
  }
}

async function restoreTimelineEvent(eventId) {
  try {
    const response = await fetch(`api/events/${encodeURIComponent(eventId)}/restore`, {
      method: 'POST',
      headers: {'Accept': 'application/json'}
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    $('timelineUndo')?.classList.remove('is-visible');
    await load();
  } catch (_) {
    const toast = $('timelineUndo');
    if (toast) toast.querySelector('span').textContent = '撤销失败，请稍后重新打开面板';
  }
}

function renderTimeline(events) {
  $('eventCount').textContent = `${events.length} 个节点`;
  if (!events.length) {
    $('timeline').innerHTML = '<div class="timeline-empty"><i data-lucide="route"></i><strong>旅程还没有开始</strong></div>';
    return;
  }
  $('timeline').innerHTML = events.map(event => `
    <article class="tnode">
      <span class="tdot"></span>
      <div class="trow"><strong class="taction">${esc(EVENT_NAMES[event.event_type] || event.event_type)}</strong><span class="trow-actions"><time class="ttime">${esc(dateTime(event.occurred_at, true))}</time><button type="button" class="timeline-hide" aria-label="从时间线隐藏这个节点" title="从时间线隐藏" onclick="hideTimelineEvent(this, '${esc(event.event_id || '')}')">×</button></span></div>
      <div class="tloc">${esc(event.place_name || '')}</div>
      ${eventWeather(event) ? `<div class="tweather">${esc(eventWeather(event))}</div>` : ''}
      ${event.summary ? `<p class="tsummary">${esc(event.summary)}</p>` : ''}
      ${timelineStreetView(event)}
      ${timelineQuote(event)}
      ${timelinePostcard(event)}
    </article>`).join('');
}

function renderStats(journey) {
  if (!journey) {
    $('journeyStats').innerHTML = '<div class="stub-empty">还没有正在进行的旅程</div>';
    return;
  }
  $('journeyStats').innerHTML = `
    <div class="stub-head"><strong>${esc(journey.title)}</strong><span>on the road</span></div>
    <div class="stub-grid">
      <div class="stub-item"><small>开始时间</small><b>${esc(dateTime(journey.started_at, true))}</b></div>
      <div class="stub-item"><small>持续时间</small><b>${esc(duration(journey.started_at))}</b></div>
      <div class="stub-item"><small>累计移动</small><b>${esc(number((journey.distance_m || 0) / 1000, ' km'))}</b></div>
      <div class="stub-item"><small>实际街景</small><b>${esc(journey.scene_count || 0)} 次</b></div>
      <div class="stub-item"><small>到访节点</small><b>${esc(journey.visited_count || 0)} 处</b></div>
      <div class="stub-item"><small>当前坐标</small><b>${Number(journey.latitude).toFixed(3)}, ${Number(journey.longitude).toFixed(3)}</b></div>
    </div>`;
}

function renderArchives(archives) {
  $('archiveCount').textContent = `${archives.length} 段`;
  if (!archives.length) {
    $('archiveList').innerHTML = '<div class="archive-empty">还没有旅程被收进档案里</div>';
    return;
  }
  $('archiveList').innerHTML = archives.map(item => `
    <a class="archive-card" href="api/journeys/${encodeURIComponent(item.journey_id)}" target="_blank" rel="noopener">
      <span class="archive-icon"><i data-lucide="map-pinned"></i></span>
      <span><strong class="archive-name">${esc(item.title)}</strong><span class="archive-meta">${esc(dateTime(item.started_at, true))} · ${esc(duration(item.started_at, item.ended_at))} · ${esc(item.visited_count)} 个节点</span></span>
      <i data-lucide="chevron-right"></i>
    </a>`).join('');
}

async function load() {
  $('refreshBtn').classList.add('loading');
  try {
    const response = await fetch(`api/snapshot/${encodeURIComponent(travelerId)}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const journey = data.journey;
    const events = data.events || [];
    renderHero(journey);
    renderWeather(journey);
    renderWords(events);
    renderTimeline(events);
    renderStats(journey);
    renderArchives(data.archives || []);
    $('connection').textContent = journey ? `旅程档案已连接 · ${travelerId}` : `旅程档案已连接 · 等待出发`;
    $('connection').classList.remove('error');
  } catch (error) {
    $('connection').textContent = `暂时无法读取旅程档案：${error.message}`;
    $('connection').classList.add('error');
    $('statusTag').className = 'hero-tag error';
    $('statusTag').querySelector('b').textContent = '连接失败';
  } finally {
    $('refreshBtn').classList.remove('loading');
    if (window.lucide) lucide.createIcons();
  }
}

async function bootstrap() {
  try {
    const response = await fetch('api/config', {cache: 'no-store'});
    if (response.ok) {
      const config = await response.json();
      travelerName = config.traveler_name || travelerName;
      companionName = config.companion_name || companionName;
      if (!travelerQuery) travelerId = config.default_traveler_id || travelerId;
    }
  } catch (_) {
    // Keep the original 小小与程渝 defaults when configuration is unavailable.
  }
  document.title = `${travelerName}在路上`;
  $('travelTitle').textContent = `${travelerName}在路上`;
  $('travelSubtitle').textContent = `${companionName}与${travelerName}的现实漫游`;
  $('heroEmptyText').textContent = `等${travelerName}想去某个真实的地方看看，这里就会亮起来。`;
  $('wordsTitle').textContent = `${travelerName}的话`;
  await load();
}

$('refreshBtn').addEventListener('click', load);
bootstrap();
