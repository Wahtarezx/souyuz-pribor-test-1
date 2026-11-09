const $ = (id) => document.getElementById(id);
const labels = {pending: 'Ожидает ответа', completed: 'Черновик готов', failed: 'Ошибка'};
let current = null;
let bundle = null;
let examples = [];
let selected = 0;

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = !message;
}

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2));
  }
  return data;
}

async function run(button, action) {
  button.disabled = true;
  notice('');
  try { await action(); } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); notice('Скопировано в буфер обмена.'); }
  catch { notice('Браузер запретил копирование. Выделите текст вручную.', true); }
}

async function show(draft) {
  current = draft;
  $('product').value = JSON.stringify(draft.product, null, 2);
  bundle = null;
  $('empty').hidden = true;
  $('pending').hidden = draft.status !== 'pending' || draft.provider !== 'manual';
  $('completed').hidden = draft.status !== 'completed';
  $('status').textContent = labels[draft.status];
  $('completion').value = '';
  if (draft.status === 'pending' && draft.provider === 'manual') {
    const request = await api(`/api/drafts/${draft.id}/request`);
    if (current.id !== draft.id) return;
    bundle = request;
    $('request-preview').textContent = JSON.stringify(bundle, null, 2);
  } else if (draft.status === 'completed') {
    const card = draft.result;
    $('seo-title').textContent = card.seo_title;
    $('seo-description').textContent = card.seo_description;
    $('title-count').textContent = `${[...card.seo_title].length} / 70`;
    $('description-count').textContent = `${[...card.seo_description].length} знаков`;
    $('commercial').textContent = card.commercial_block;
    $('provenance').textContent = `${draft.provider === 'manual' ? 'ChatGPT · ручной импорт' : draft.model} · нужна проверка`;
    $('specs').replaceChildren(...card.characteristics.map((item) => {
      const row = document.createElement('div');
      row.append(node('dt', item.name), node('dd', item.value, item.value === 'данных нет' ? 'unknown' : ''));
      return row;
    }));
    $('queries').replaceChildren(...card.search_queries.map((q) => node('span', q, 'chip')));
    $('missing').replaceChildren(...card.missing_fields.map((f) => node('li', f)));
    $('missing-block').hidden = !card.missing_fields.length;
    $('evidence').replaceChildren(...card.evidence.map((e) => node('li', `${e.field}: «${e.quote}»`)));
  } else if (draft.status === 'failed') { notice(draft.error, true); }
}

async function history() {
  const items = await api('/api/drafts');
  $('history-list').replaceChildren(...items.map((item) => {
    const button = node('button', '', 'history-row');
    button.type = 'button';
    button.append(node('span', item.name), node('span', `${labels[item.status]} · ${item.provider === 'manual' ? 'ChatGPT' : 'OpenAI API'}`, 'history-meta'));
    button.addEventListener('click', () => run(button, async () => {
      await show(await api(`/api/drafts/${item.id}`));
      $('status').scrollIntoView({behavior: 'smooth', block: 'center'});
    }));
    return button;
  }));
  if (!items.length) $('history-list').append(node('p', 'Заданий пока нет.', 'hint'));
}

function selectExample(index) {
  selected = index;
  $('product').value = JSON.stringify(examples[index].product, null, 2);
  [...$('examples').children].forEach((b, i) => b.classList.toggle('active', i === index));
}

$('form').addEventListener('submit', (event) => {
  event.preventDefault();
  run($('create'), async () => {
    const product = JSON.parse($('product').value);
    const provider = $('provider').value;
    if (provider === 'openai') notice('Модель готовит текст. Это может занять около минуты.');
    try {
      await show(await api('/api/drafts', {method: 'POST', body: JSON.stringify({product, provider})}));
      notice(provider === 'manual' ? 'Задание сохранено. Передайте запрос ChatGPT.' : 'Черновик сохранён. Проверьте формулировки перед публикацией.');
    } finally { await history(); }
  });
});
$('provider').addEventListener('change', () => {
  const manual = $('provider').value === 'manual';
  $('provider-note').textContent = manual ? 'Сервис подготовит запрос. Передайте его ChatGPT и импортируйте ответ ниже.' : 'Автоматическая генерация через OpenAI. Требуется ключ в .env.';
  $('create').textContent = manual ? 'Подготовить запрос ↗' : 'Создать черновик ↗';
});
$('copy-request').addEventListener('click', () => copy(JSON.stringify(bundle, null, 2)));
$('copy-json').addEventListener('click', () => copy(JSON.stringify(current.result, null, 2)));
$('copy-md').addEventListener('click', () => run($('copy-md'), async () => {
  const response = await fetch(`/api/drafts/${current.id}/markdown`);
  if (!response.ok) throw new Error('Не удалось получить Markdown');
  await copy(await response.text());
}));
$('import').addEventListener('click', () => run($('import'), async () => {
  const payload = JSON.parse($('completion').value);
  await show(await api(`/api/drafts/${current.id}/result`, {method: 'POST', body: JSON.stringify(payload)}));
  notice('Проверки пройдены. Черновик сохранён.');
  await history();
}));
$('upload').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 100000) { notice('Файл ответа должен быть меньше 100 КБ.', true); return; }
  $('completion').value = await file.text();
});
$('refresh').addEventListener('click', () => run($('refresh'), history));
$('demo').addEventListener('click', () => run($('demo'), async () => {
  const example = examples[selected];
  if (!example) throw new Error('Примеры ещё не загружены');
  const draft = await api('/api/drafts', {method: 'POST', body: JSON.stringify({product: example.product, provider: 'manual'})});
  await show(await api(`/api/drafts/${draft.id}/result`, {method: 'POST', body: JSON.stringify({draft_id: draft.id, input_hash: draft.input_hash, content: example.content})}));
  notice('Сохранён готовый пример ответа ChatGPT. Внешний API не вызывался.');
  await history();
}));

async function init() {
  try {
    const [config, data] = await Promise.all([api('/api/config'), api('/api/examples')]);
    examples = data;
    $('examples').replaceChildren(...examples.map((item, i) => {
      const button = node('button', item.product.name.split(' ').slice(0, 2).join(' '), 'example');
      button.type = 'button';
      button.addEventListener('click', () => selectExample(i));
      return button;
    }));
    if (examples.length) selectExample(0);
    $('provider').value = config.default_provider;
    $('provider').querySelector('[value="openai"]').disabled = !config.openai_available;
    if (!config.openai_available && config.default_provider === 'openai') $('provider').value = 'manual';
    $('provider').dispatchEvent(new Event('change'));
    await history();
  } catch (error) { notice(`Не удалось загрузить сервис: ${error.message}`, true); }
}
init();
