import { renderPipeline } from './pipeline.js';
import { renderCredentials } from './credentials.js';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { config: null, documents: [], view: 'queue', selected: null, queueJob: null, dirty: false, input: 'file', request: 0, busy: false };
const draftKey = 'delta-mind-review-draft';
let leavePending = false;
const statuses = { pending: 'Chờ duyệt', approved: 'Đã duyệt', rejected: 'Đã từ chối', withdrawn: 'Đã thu hồi' };
const actions = { import: 'Tiếp nhận tài liệu', approve: 'Phê duyệt', reject: 'Từ chối', reopen: 'Mở lại để duyệt', withdraw: 'Thu hồi khỏi kho', ingest: 'Tiếp nhận tài liệu', create: 'Tiếp nhận tài liệu', edit: 'Cập nhật nội dung', update: 'Cập nhật nội dung' };
const kinds = { text: 'Văn bản', file: 'Tệp tải lên', web: 'Trang web' };
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (['value', 'checked', 'disabled', 'required', 'readOnly'].includes(key)) node[key] = value;
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
function button(text, callback, className = 'button') { const node = el('button', { type: 'button', class: className }, text); node.addEventListener('click', callback); return node; }
function badge(status) { return el('span', { class: `badge ${statuses[status] ? status : 'neutral'}` }, statuses[status] || status); }
function formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(date); }
function locationLabel(value) {
  if (!value) return '';
  if (typeof value === 'string') return value;
  const parts = [];
  if (value.page != null) parts.push(`Trang ${value.page}`);
  else if (value.kind === 'reviewed_text') parts.push('Nội dung đã hiệu chỉnh');
  else if (value.kind === 'document_text') parts.push('Nội dung trích xuất');
  if (Number.isInteger(value.start) && Number.isInteger(value.end)) parts.push(`ký tự ${value.start}–${value.end}`);
  return parts.join(' · ');
}
function message(text, error = false, target = $('#global-message')) { target.replaceChildren(document.createTextNode(text)); target.className = `notice${error ? ' error' : ''}`; target.hidden = !text; }
function safeURL(value) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; } }
async function api(path, options = {}, refreshed = false) {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', state.config?.csrf_token || '');
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 403 && data.detail === 'Phiên làm việc đã đổi. Tải lại trang.' && !refreshed) {
    state.config = await api('/api/config');
    return api(path, options, true);
  }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Không thể hoàn tất yêu cầu (${response.status}).`);
  return data;
}
function setBusy(node, busy, text) { node.disabled = busy; node.classList.toggle('busy', busy); if (text) node.textContent = text; }
function metadataFields(prefix, values = {}, readonly = false) {
  const grid = el('div', { class: 'metadata-grid' });
  const field = (name, label, options = {}) => {
    const input = el('input', { id: `${prefix}-${name}`, name, type: 'text', value: values[name] ?? options.defaultValue ?? '', disabled: readonly, ...options });
    input.removeAttribute('defaultValue');
    grid.append(el('label', { class: name === 'title' ? 'wide' : null }, label, input));
    return input;
  };
  field('title', 'Tên tài liệu', { placeholder: 'Tự lấy từ nguồn nếu để trống' });
  field('collection', 'Bộ sưu tập', { defaultValue: 'general', required: true });
  field('document_version', 'Phiên bản', { defaultValue: '1', required: true });
  field('source_id', 'Mã nguồn ổn định', { placeholder: 'Tự tạo nếu để trống' });
  const sensitive = el('input', { name: 'time_sensitive', type: 'checkbox', checked: values.time_sensitive, disabled: readonly });
  grid.append(el('label', { class: 'check-label metadata-sensitive' }, sensitive, 'Nội dung phụ thuộc thời gian hiệu lực'));
  const from = field('effective_from', 'Có hiệu lực từ', { type: 'date', required: Boolean(values.time_sensitive) });
  field('effective_to', 'Hết hiệu lực từ (không bao gồm)', { type: 'date' });
  sensitive.addEventListener('change', () => { from.required = sensitive.checked; });
  grid.append(el('p', { class: 'field-hint wide' }, 'Chỉ bắt buộc ngày bắt đầu khi nội dung phụ thuộc thời gian. Để trống ngày kết thúc nếu hiệu lực không có hạn định.'));
  return grid;
}
function metadataPayload(form) {
  const data = new FormData(form), result = {};
  for (const name of ['title', 'collection', 'source_id', 'document_version']) result[name] = String(data.get(name) || '').trim();
  for (const name of ['effective_from', 'effective_to']) result[name] = data.get(name) || null;
  result.time_sensitive = data.get('time_sensitive') === 'on';
  if (result.effective_from && result.effective_to && result.effective_to <= result.effective_from) throw new Error('Ngày hết hiệu lực phải sau ngày bắt đầu.');
  return result;
}
function updateMetrics() {
  const counts = Object.fromEntries(Object.keys(statuses).map(status => [status, state.documents.filter(doc => doc.status === status).length]));
  $('#metric-pending').textContent = counts.pending; $('#queue-count').textContent = counts.pending;
  $('#metric-approved').textContent = counts.approved; $('#metric-total').textContent = state.documents.length;
  $('#metric-findings').textContent = state.documents.filter(doc => doc.status === 'pending' && doc.quality?.findings?.some(finding => ['warning', 'error'].includes(finding.severity))).length;
}
function reviewProgress() {
  if (!state.queueJob) return null;
  const job = state.queueJob, docs = state.documents.filter(doc => job.document_ids.includes(doc.id));
  const pending = docs.filter(doc => doc.status === 'pending').sort((a, b) => (a.quality?.score ?? 0) - (b.quality?.score ?? 0));
  const approved = docs.filter(doc => doc.status === 'approved').length;
  const panel = el('section', {class:'notice pipeline-next-step'}, el('strong', {}, 'Bước 2 · Duyệt tài liệu'), el('p', {}, `${pending.length} chờ duyệt · ${approved} đã duyệt · ${docs.length - pending.length - approved} từ chối/thu hồi.`));
  if (pending.length) panel.append(button('Duyệt tài liệu tiếp theo →', () => selectDocument((pending.find(doc => doc.id !== state.selected?.id) || pending[0]).id), 'button primary'));
  else if (approved) panel.append(el('p', {}, 'Đã xử lý hết hàng chờ của phiên. Tiếp tục chọn provider và tạo index; chưa gọi API ở bước chuyển trang.'), button('Tiếp tục: tạo index →', () => { if (!state.busy) setView('pipeline', job); }, 'button primary'));
  else panel.append(el('p', {}, 'Chưa có tài liệu được duyệt để tạo index. Xem lại quyết định hoặc thu thập nguồn khác.'), button('Quay lại lấy nguồn →', () => setView('pipeline', job)));
  return panel;
}
function renderList() {
  const normalized = value => String(value || '').toLocaleLowerCase('vi').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');
  const query = normalized($('#filter-text').value), status = $('#filter-status').value;
  const documents = state.documents.filter(doc => (!state.queueJob || state.queueJob.document_ids.includes(doc.id)) && (status === 'all' || doc.status === status) && normalized(`${doc.title} ${doc.source_id} ${doc.collection}`).includes(query));
  if (status === 'pending') documents.sort((a, b) => (a.quality?.score ?? 0) - (b.quality?.score ?? 0));
  let scopeBanner = $('#queue-job-banner');
  if (!scopeBanner) { scopeBanner = el('div', {id:'queue-job-banner', class:'notice queue-job-banner'}); $('#document-list').before(scopeBanner); }
  scopeBanner.hidden = !state.queueJob;
  scopeBanner.replaceChildren();
  if (state.queueJob) scopeBanner.append(el('p', {}, `Tài liệu từ phiên crawl · ${state.queueJob.collection} · ${state.queueJob.id.slice(0, 8)}`), button('Xem toàn bộ hàng chờ', () => { state.queueJob = null; renderList(); }, 'button'));
  if (state.queueJob && !state.selected) scopeBanner.append(reviewProgress());
  const list = $('#document-list'); list.replaceChildren(); $('#list-count').textContent = `${documents.length} tài liệu`;
  if (!documents.length) {
    if (state.queueJob && status === 'pending' && !state.documents.some(doc => state.queueJob.document_ids.includes(doc.id) && doc.status === 'pending')) {
      list.append(el('p', {class:'notice'}, 'Đã xử lý hết tài liệu chờ duyệt của phiên này. Xem quyết định hoặc tiếp tục tạo index trong phần chi tiết.'));
      return;
    }
    const isEmpty = !state.documents.length;
    list.append(el('div', { class: 'empty-state' }, el('div', { class: 'empty-art', 'aria-hidden': 'true' }), el('h3', {}, isEmpty ? 'Bắt đầu từ một tài liệu đáng tin cậy' : 'Không có tài liệu phù hợp'), el('p', {}, isEmpty ? 'Thêm nguồn đầu tiên để trích xuất và kiểm tra. Bạn luôn là người quyết định tài liệu nào được đưa vào kho.' : 'Thay đổi bộ lọc hoặc thêm tài liệu mới để tiếp tục kiểm duyệt.'), button(isEmpty ? '＋ Thêm tài liệu đầu tiên' : 'Thêm tài liệu', openIngest, 'button')));
    return;
  }
  for (const doc of documents) {
    const name = button(doc.title || 'Tài liệu chưa đặt tên', () => selectDocument(doc.id), 'document-name');
    name.append(el('span', { class: 'document-origin' }, `${kinds[doc.source_kind] || 'Nguồn tài liệu'} · Phiên bản ${doc.document_version || '—'}`));
    const row = el('div', { class: `document-row${state.selected?.id === doc.id ? ' selected' : ''}` }, name, el('span', { class: 'document-collection' }, doc.collection), badge(doc.status), el('span', { class: 'quality-mini', title: 'Chất lượng trích xuất, không phải xác suất đúng' }, `${doc.quality?.score ?? '—'}/100`), el('span', { class: 'document-date' }, formatDate(doc.updated_at)));
    list.append(row);
  }
}
async function refreshDocuments() {
  const refresh = $('#refresh-documents'); refresh.disabled = true;
  try { const data = await api('/api/documents'); state.documents = data.documents; updateMetrics(); renderList(); }
  catch (error) { message(error.message, true); if (!state.documents.length) $('#document-list').replaceChildren(el('div', { class: 'empty-state' }, el('h3', {}, 'Chưa tải được danh sách'), el('p', {}, 'Kiểm tra kết nối máy chủ rồi thử lại.'), button('Thử lại', boot))); }
  finally { refresh.disabled = false; }
}
function readDraft() { try { return JSON.parse(sessionStorage.getItem(draftKey) || 'null'); } catch { return null; } }
function clearDraft() { try { sessionStorage.removeItem(draftKey); } catch { /* The form still works when browser storage is unavailable. */ } }
function storeDraft(form, doc) {
  try { sessionStorage.setItem(draftKey, JSON.stringify({ id: doc.id, revision: doc.revision, fields: Object.fromEntries(new FormData(form)), time_sensitive: $('[name="time_sensitive"]', form).checked })); return true; }
  catch { return false; }
}
async function allowLeave() {
  if (!state.dirty) return true;
  if (leavePending) return false;
  leavePending = true;
  const dialog = $('#leave-dialog'); dialog.returnValue = 'stay';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => {
      leavePending = false;
      const discard = dialog.returnValue === 'discard';
      if (discard) { clearDraft(); state.dirty = false; }
      resolve(discard);
    }, { once: true });
    dialog.showModal();
  });
}
async function closeDetail() { if (state.busy || !await allowLeave()) return; state.request++; state.selected = null; state.dirty = false; $('#document-detail').hidden = true; $('#review-layout').classList.remove('has-detail'); renderList(); }
async function setView(view, preset = null) {
  if (view !== state.view && !await allowLeave()) return false;
  if (view !== state.view) { state.dirty = false; state.selected = null; state.request++; $('#document-detail').hidden = true; $('#review-layout').classList.remove('has-detail'); }
  if (view !== state.view) message('');
  state.view = view;
  state.queueJob = null;
  history.replaceState(null, "", ["pipeline", "settings"].includes(view) ? `#${view}` : location.pathname);
  for (const item of $$('[data-view]')) { const selected = item.dataset.view === view; item.classList.toggle('active', selected); if (selected) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current'); }
  const settings = { pipeline: ['Crawl & RAG pipeline', 'Pipeline', 'Thu thập nguồn → người duyệt → embedding → evidence.'], settings: ['Cấu hình API key', 'Cấu hình API key', 'Quản lý riêng key BTC và bộ key của các nhà cung cấp.'], queue: ['Duyệt tài liệu RAG', 'Hàng chờ duyệt', 'Kiểm tra nguồn, đối chiếu nội dung, rồi đưa tri thức vào sử dụng.'], library: ['Kho tri thức đã duyệt', 'Kho tri thức', 'Quản lý những nguồn đã được kiểm duyệt và sẵn sàng truy hồi.'], search: ['Tra cứu có dẫn nguồn', 'Tra cứu nguồn', 'Tìm đúng đoạn tài liệu, kiểm tra đúng nguồn và phiên bản.'] }[view];
  $('#page-title').textContent = settings[0]; $('#breadcrumb-current').textContent = settings[1]; $('#page-description').textContent = settings[2];
  $('#document-workspace').hidden = ['search', 'settings', 'pipeline'].includes(view); $('#search-workspace').hidden = view !== 'search';
  $('#credentials-workspace').hidden = view !== 'settings'; $('#open-ingest').hidden = ['settings', 'pipeline'].includes(view);
  $('#pipeline-workspace').hidden = view !== 'pipeline';
  if (view === 'pipeline') await renderPipeline($('#pipeline-workspace'), api, openPipelineQueue, {preset, openSettings: () => setView('settings'), openSearch: async collection => { if (await setView('search')) { $('#retrieval-form [name="collection"]').value = collection; updateExportLink(); $('#retrieval-query').focus(); } }}); else $('#pipeline-workspace').replaceChildren();
  if (view === 'settings') await renderCredentials($('#credentials-workspace'), api); else $('#credentials-workspace').replaceChildren();
  $('#list-title').textContent = view === 'library' ? 'Tài liệu trong kho' : 'Hàng chờ kiểm duyệt';
  $('#list-subtitle').textContent = view === 'library' ? 'Nguồn được duyệt và quản lý theo phiên bản, hiệu lực.' : 'Tài liệu chỉ được truy hồi sau khi bạn phê duyệt.';
  if (!['search', 'settings', 'pipeline'].includes(view)) { $('#filter-status').value = view === 'library' ? 'approved' : 'pending'; $('#filter-text').value = ''; renderList(); }
  return true;
}
async function openPipelineQueue(job = null) {
  const data = await api('/api/documents');
  const scoped = job ? data.documents.filter(doc => job.document_ids.includes(doc.id)) : data.documents;
  if (job && !scoped.length) throw new Error('Phiên này chưa có tài liệu để duyệt. Nhập URL nguồn và chạy crawl lại.');
  if (!await setView('queue')) return;
  state.documents = data.documents; state.queueJob = job; updateMetrics();
  const pending = scoped.filter(doc => doc.status === 'pending').sort((a, b) => (a.quality?.score ?? 0) - (b.quality?.score ?? 0));
  $('#filter-status').value = pending.length || !job ? 'pending' : 'all';
  renderList();
  if (job) {
    message(pending.length ? `Bước tiếp theo: đối chiếu nguồn, sửa nếu cần, rồi phê duyệt hoặc từ chối ${pending.length} tài liệu của phiên này.` : 'Phiên này không còn tài liệu chờ duyệt. Bạn có thể xem lại các quyết định bên dưới.');
    await selectDocument((pending[0] || scoped[0]).id);
  }
}
async function selectDocument(id) {
  if (state.busy || !await allowLeave()) return;
  state.dirty = false; const request = ++state.request;
  const detail = $('#document-detail'); detail.hidden = false; detail.replaceChildren(el('div', { class: 'loading' }, 'Đang mở tài liệu…'));
  $('#review-layout').classList.add('has-detail');
  try { const doc = await api(`/api/documents/${encodeURIComponent(id)}`); if (request !== state.request) return; state.selected = doc; renderDetail(doc); renderList(); if (window.innerWidth <= 960) detail.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  catch (error) { if (request !== state.request) return; detail.replaceChildren(el('div', { class: 'detail-body' }, el('p', { class: 'notice error' }, error.message), button('Đóng chi tiết', closeDetail))); }
}
function renderDetail(doc) {
  const detail = $('#document-detail'), pending = doc.status === 'pending', findings = doc.quality?.findings || [];
  state.dirty = false; detail.replaceChildren();
  const close = button('×', closeDetail, 'icon-button'); close.setAttribute('aria-label', 'Đóng chi tiết tài liệu');
  detail.append(el('div', { class: 'detail-heading' }, el('div', {}, badge(doc.status), el('h2', {}, doc.title), el('p', {}, `${doc.source_id} · Phiên bản ${doc.document_version}`)), close));
  const score = Math.max(0, Math.min(100, Number(doc.quality?.score) || 0));
  detail.append(el('div', { class: 'quality-card' }, el('div', { class: 'quality-top' }, 'Chất lượng trích xuất', el('strong', {}, score, el('small', {}, ' /100'))), el('meter', { class: 'quality-meter', 'aria-label': 'Chất lượng trích xuất', min: 0, max: 100, value: score }, score), el('p', {}, 'Điểm kiểm tra cấu trúc và khả năng trích xuất; không phải xác suất nội dung đúng.'), el('div', { class: 'confidence' }, el('span', {}, 'Tính đúng của nội dung'), el('strong', {}, 'Chưa được kiểm chứng'))));
  const tabs = el('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Chi tiết nguồn' }), body = el('div', { class: 'detail-body' });
  const panels = {}, tabButtons = {};
  for (const [key, label] of [['content', 'Nội dung'], ['original', 'Nguồn gốc'], ['chunks', `Đoạn truy hồi (${doc.chunks?.length || 0})`], ['audit', 'Lịch sử']]) {
    panels[key] = el('div', { id: `detail-${key}`, role: 'tabpanel', 'aria-labelledby': `detail-tab-${key}`, hidden: key !== 'content' });
    const tab = button(label, () => activateTab(key), ''); tab.id = `detail-tab-${key}`; tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', `detail-${key}`); tab.setAttribute('aria-selected', String(key === 'content')); tab.tabIndex = key === 'content' ? 0 : -1;
    tabButtons[key] = tab; tabs.append(tab); body.append(panels[key]);
  }
  function activateTab(key) { for (const name of Object.keys(panels)) { panels[name].hidden = name !== key; tabButtons[name].setAttribute('aria-selected', String(name === key)); tabButtons[name].tabIndex = name === key ? 0 : -1; } if (key === 'original') loadOriginal(doc, panels.original); }
  setupTabKeys(tabs);
  const editForm = el('form', { id: 'edit-document' });
  const metadata = el('details', { class: 'metadata-details' }, el('summary', {}, 'Thông tin nguồn & hiệu lực'), metadataFields('edit', doc, !pending));
  editForm.append(metadata, el('p', { class: 'readonly-note' }, doc.edited ? 'Nội dung đã được người duyệt hiệu chỉnh; xem Nguồn gốc để đối chiếu bản tiếp nhận.' : 'Nội dung được trích xuất từ nguồn tiếp nhận; chưa có chỉnh sửa của người duyệt.'));
  editForm.addEventListener('invalid', event => { const section = event.target.closest('details'); if (section) section.open = true; }, true);
  if (pending) {
    editForm.append(el('label', {}, 'Nội dung dùng để tạo đoạn truy hồi', el('textarea', { name: 'text', class: 'editor-text', required: true, rows: 12 }, doc.text)), el('div', { class: 'editor-actions' }, el('small', { id: 'edit-status' }, 'Có thể chỉnh sửa trước khi duyệt.'), el('button', { type: 'submit', class: 'button', id: 'save-document' }, 'Lưu thay đổi')));
    editForm.addEventListener('input', () => { state.dirty = true; $('#edit-status').textContent = storeDraft(editForm, doc) ? 'Chưa lưu · bản nháp được giữ trong phiên này' : 'Có thay đổi chưa lưu'; });
    const draft = readDraft();
    if (draft?.id === doc.id && draft.revision === doc.revision && draft.fields) {
      for (const input of $$('input, textarea', editForm)) if (input.type === 'checkbox') input.checked = draft.time_sensitive === true; else if (typeof draft.fields[input.name] === 'string') input.value = draft.fields[input.name];
      $('[name="effective_from"]', editForm).required = draft.time_sensitive === true;
      state.dirty = true; $('#edit-status', editForm).textContent = 'Đã khôi phục bản nháp chưa lưu trong phiên này';
    } else if (draft?.id === doc.id) clearDraft();
    editForm.addEventListener('submit', event => saveDocument(event, doc));
  } else editForm.append(el('p', { class: 'readonly-note' }, doc.status === 'rejected' ? 'Nội dung bị từ chối. Mở lại hàng chờ để chỉnh sửa và kiểm duyệt lại.' : 'Bản nội dung được khóa theo phiên bản. Tiếp nhận phiên bản mới nếu cần thay đổi.'), el('pre', { class: 'source-text' }, doc.text));
  panels.content.append(editForm);
  panels.original.append(el('p', { class: 'readonly-note' }, 'Bản nguồn được lưu lúc tiếp nhận, độc lập với nội dung người duyệt đã chỉnh sửa.'), el('a', { class: 'text-link', href: `/api/documents/${encodeURIComponent(doc.id)}/original`, download: '' }, 'Tải bản gốc xuống ↗'));
  const sourceURL = safeURL(doc.source_url), sourceInfo = el('dl', { class: 'source-meta' });
  for (const [label, value] of [['Loại nguồn', kinds[doc.source_kind]], ['Tệp', doc.filename], ['Nguồn web', sourceURL], ['Tiếp nhận', formatDate(doc.created_at)], ['SHA-256', doc.source_sha256]]) if (value) sourceInfo.append(el('dt', {}, label), el('dd', {}, value));
  panels.original.append(sourceInfo);
  if (!doc.chunks?.length) panels.chunks.append(el('p', { class: 'readonly-note' }, 'Chưa có đoạn truy hồi được tạo.'));
  for (const [index, chunk] of (doc.chunks || []).entries()) panels.chunks.append(el('article', { class: 'chunk-card' }, el('header', {}, el('strong', {}, `Đoạn ${String(index + 1).padStart(2, '0')}`), el('span', {}, chunk.tokens ? `${chunk.tokens} token` : '')), el('pre', { class: 'chunk-text' }, chunk.text), el('small', { class: 'field-hint' }, locationLabel(chunk.locator))));
  for (const entry of [...(doc.audit || [])].reverse()) panels.audit.append(el('div', { class: 'audit-entry' }, el('strong', {}, entry.action === 'approve' && entry.approval_mode === 'automatic' ? 'Duyệt tự động theo quy tắc' : (actions[entry.action] || entry.action)), el('small', {}, `${entry.actor === 'local-operator' ? 'Người vận hành cục bộ' : entry.actor || 'Hệ thống'} · ${formatDate(entry.at)}`), entry.note ? el('p', {}, entry.note) : null));
  if (!doc.audit?.length) panels.audit.append(el('p', { class: 'readonly-note' }, 'Chưa có hoạt động được ghi nhận.'));
  detail.append(tabs, body);
  const findingsSection = el('section', { class: 'findings', 'aria-label': 'Các điểm cần kiểm tra' }, el('div', { class: 'section-kicker' }, `ĐIỂM CẦN KIỂM TRA · ${findings.length}`));
  if (!findings.length) findingsSection.append(el('p', { class: 'field-hint' }, 'Chưa phát hiện vấn đề kỹ thuật. Vẫn cần đối chiếu tính đúng của nội dung với nguồn.'));
  for (const finding of findings) findingsSection.append(el('article', { class: `finding ${['warning', 'error'].includes(finding.severity) ? finding.severity : ''}` }, el('strong', {}, ({ error: 'Cần sửa trước khi duyệt', warning: 'Cần đối chiếu', info: 'Thông tin' })[finding.severity] || 'Thông tin'), el('p', {}, finding.message), finding.snippet ? el('blockquote', {}, finding.snippet) : null, locationLabel(finding.locator) ? el('small', {}, locationLabel(finding.locator)) : null));
  if (doc.crawl) detail.append(el('section', { class: 'notice' }, el('strong', {}, 'Nguồn từ phiên crawl'), el('p', {}, `Phiên ${doc.crawl.job_id} · trạng thái upstream: ${doc.crawl.upstream_status || 'chưa đánh giá'}. Quyết định của Human Mind là độc lập.`), doc.crawl.assessment ? el('pre', {}, JSON.stringify(doc.crawl.assessment, null, 2)) : el('p', {}, 'Chưa có AI assessment; cần người đối chiếu nguồn.')));
  if (doc.crawl?.scope_reason) detail.append(el('p', { class: 'notice' }, `Lý do AI đánh giá phạm vi: ${doc.crawl.scope_reason}`));
  detail.append(findingsSection, decisionForm(doc, findings));
  const progress = reviewProgress();
  if (progress) { progress.id = 'review-next-action'; detail.append(progress); }
}
async function loadOriginal(doc, panel) {
  if (panel.dataset.loaded) return; panel.dataset.loaded = 'true';
  $('.original-preview', panel)?.remove();
  const url = `/api/documents/${encodeURIComponent(doc.id)}/original?inline=1`;
  if (doc.mime === 'application/pdf' || /\.pdf$/i.test(doc.filename || '')) { panel.append(el('iframe', { class: 'source-frame', src: url, title: `Bản PDF gốc: ${doc.title}` })); return; }
  const preview = el('pre', { class: 'source-text original-preview' }, 'Đang tải bản nguồn…'); panel.append(preview);
  try { const response = await fetch(url); if (!response.ok) throw new Error('Không tải được bản gốc. Hãy thử liên kết tải xuống.'); preview.textContent = await response.text(); }
  catch (error) { preview.textContent = error.message; delete panel.dataset.loaded; }
}
async function saveDocument(event, doc) {
  event.preventDefault(); if (state.busy) return;
  const form = event.currentTarget, save = $('#save-document');
  try {
    const data = { revision: doc.revision, ...metadataPayload(form), text: new FormData(form).get('text') };
    state.busy = true; setBusy(save, true, 'Đang lưu…');
    const updated = await api(`/api/documents/${encodeURIComponent(doc.id)}`, { method: 'PATCH', body: JSON.stringify(data) });
    clearDraft(); state.selected = updated; renderDetail(updated); await refreshDocuments(); message('Đã lưu nội dung và kiểm tra lại chất lượng trích xuất.');
  } catch (error) { message(error.message, true); setBusy(save, false, 'Lưu thay đổi'); }
  finally { state.busy = false; }
}
function decisionForm(doc, findings) {
  if (doc.status === 'withdrawn') return el('div', { class: 'decision-box' }, el('h3', {}, 'Tài liệu đã được thu hồi'), el('p', { class: 'readonly-note' }, 'Nguồn này không còn tham gia truy hồi. Tiếp nhận phiên bản mới nếu cần đưa nội dung trở lại kho.'));
  const pending = doc.status === 'pending', blocked = findings.some(item => item.severity === 'error');
  const form = el('form', { class: 'decision-box' }, el('h3', {}, pending ? 'Quyết định kiểm duyệt' : 'Quản lý trạng thái'));
  form.append(el('div', { class: 'decision-fields' }, el('label', {}, 'Người kiểm duyệt', el('input', { name: 'actor', required: true, placeholder: 'Họ tên hoặc mã người duyệt', autocomplete: 'name' })), el('label', {}, 'Ghi chú quyết định', el('textarea', { name: 'note', rows: 2, placeholder: 'Ghi lại căn cứ, nội dung đã đối chiếu hoặc lý do…' }))));
  if (pending && findings.some(item => item.severity === 'warning')) form.append(el('label', { class: 'check-label' }, el('input', { name: 'acknowledge_findings', type: 'checkbox' }), 'Tôi đã đối chiếu các cảnh báo với nguồn và chịu trách nhiệm về quyết định duyệt.'));
  const decisions = pending ? ['approve', 'reject'] : doc.status === 'approved' ? ['withdraw'] : ['reopen'];
  if (doc.status === 'approved') form.append(el('p', { class: 'notice warning' }, 'Thu hồi sẽ loại toàn bộ các đoạn của phiên bản này khỏi truy hồi. Hãy ghi lý do trước khi chọn Thu hồi khỏi kho.'));
  const controls = el('div', { class: 'decision-actions' });
  for (const action of decisions) controls.append(el('button', { type: 'submit', name: 'action', value: action, class: `button ${action === 'approve' || action === 'reopen' ? 'primary' : 'danger'}`, disabled: action === 'approve' && blocked }, actions[action]));
  form.append(controls);
  if (pending && blocked) form.append(el('p', { class: 'decision-warning' }, 'Còn lỗi chặn. Sửa nội dung hoặc thông tin nguồn rồi lưu lại trước khi phê duyệt.'));
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy) return;
    if (state.dirty) { message('Hãy lưu nội dung đã chỉnh sửa trước khi đưa ra quyết định.', true); $('#save-document')?.focus(); return; }
    const action = event.submitter?.value; if (!action) return;
    const data = new FormData(form), acknowledged = data.get('acknowledge_findings') === 'on';
    if (action === 'approve' && findings.some(item => item.severity === 'warning') && !acknowledged) { message('Cần xác nhận đã đối chiếu các cảnh báo trước khi phê duyệt.', true); $('[name="acknowledge_findings"]', form).focus(); return; }
    const note = String(data.get('note') || '').trim();
    if (['reject', 'withdraw'].includes(action) && !note) { message('Vui lòng ghi lý do cho quyết định này.', true); $('[name="note"]', form).focus(); return; }
    try {
      state.busy = true; for (const node of $$('button', form)) node.disabled = true;
      const updated = await api(`/api/documents/${encodeURIComponent(doc.id)}/decision`, { method: 'POST', body: JSON.stringify({ revision: doc.revision, action, actor: String(data.get('actor')).trim(), note, acknowledge_findings: acknowledged }) });
      state.selected = updated; await refreshDocuments(); renderDetail(updated); message(`Đã ${actions[action].toLocaleLowerCase('vi')} tài liệu “${updated.title}”.`);
      $('#review-next-action')?.scrollIntoView({behavior:'smooth',block:'center'});
    } catch (error) { message(error.message, true); for (const node of $$('button', form)) node.disabled = node.value === 'approve' && blocked; }
    finally { state.busy = false; }
  });
  return form;
}
function setupTabKeys(container) {
  container.addEventListener('keydown', event => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    const items = $$('[role="tab"]', container), index = items.indexOf(document.activeElement); if (index < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    items[next].click(); items[next].focus();
  });
}
function inputMode(mode) {
  state.input = mode;
  for (const item of $$('[data-input]')) { const selected = item.dataset.input === mode; item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1; }
  for (const key of ['file', 'text', 'web']) $('#input-' + key).hidden = key !== mode;
  $('#source-file').required = mode === 'file'; $('#source-text').required = mode === 'text'; $('#source-url').required = mode === 'web';
  $('#source-file').disabled = mode !== 'file'; $('#source-text').disabled = mode !== 'text'; $('#source-url').disabled = mode !== 'web';
  message('', false, $('#ingest-error'));
}
function openIngest() { if (state.busy) return; if (!state.config) { message('Chưa kết nối được máy chủ. Hãy làm mới danh sách rồi thử lại.', true); return; } $('#ingest-dialog').showModal(); }
$('#ingest-metadata').append(metadataFields('new'));
$('#open-ingest').addEventListener('click', openIngest);
$('#close-ingest').addEventListener('click', () => $('#ingest-dialog').close());
for (const node of $$('[data-input]')) node.addEventListener('click', () => inputMode(node.dataset.input));
setupTabKeys($('.input-tabs')); inputMode('file');
$('#ingest-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, submit = $('#submit-ingest'); if (submit.disabled) return;
  try {
    const metadata = metadataPayload(form), data = new FormData(form); let body, path;
    if (state.input === 'file') {
      const file = data.get('file'); if (!file?.size) throw new Error('Vui lòng chọn tệp không rỗng.');
      if (file.size > (state.config.limits?.upload_bytes || 10 * 1024 * 1024)) throw new Error('Tệp vượt quá giới hạn 10 MB.');
      body = new FormData(); body.set('file', file); body.set('metadata', JSON.stringify(metadata)); path = 'upload';
    } else { path = state.input; body = JSON.stringify({ ...metadata, ...(path === 'text' ? { text: data.get('text') } : { url: String(data.get('url')).trim() }) }); }
    setBusy(submit, true, 'Đang trích xuất…'); message('', false, $('#ingest-error'));
    const doc = await api(`/api/documents/${path}`, { method: 'POST', body });
    $('#ingest-dialog').close(); form.reset(); inputMode('file'); $('#new-effective_from').required = false;
    if (!state.dirty && !state.busy) { await setView('queue'); await refreshDocuments(); await selectDocument(doc.id); } else await refreshDocuments(); message('Đã tiếp nhận tài liệu. Kiểm tra nội dung và các điểm cần đối chiếu trước khi duyệt.');
  } catch (error) { message(error.message, true, $('#ingest-error')); }
  finally { setBusy(submit, false, 'Trích xuất & đưa vào hàng chờ'); }
});
for (const item of $$('[data-view]')) item.addEventListener('click', async () => { if (!state.busy) await setView(item.dataset.view); });
$('#filter-text').addEventListener('input', renderList); $('#filter-status').addEventListener('change', renderList);
$('#refresh-documents').addEventListener('click', () => state.config ? refreshDocuments() : boot());
const searchForm = $('#retrieval-form');
const today = new Date(); today.setMinutes(today.getMinutes() - today.getTimezoneOffset()); $('[name="as_of"]', searchForm).value = today.toISOString().slice(0, 10);
function updateExportLink() { const data = new FormData(searchForm); $('#export-link').href = `/api/export?${new URLSearchParams({ collection: String(data.get('collection')).trim() || 'general', as_of: data.get('as_of') || today.toISOString().slice(0, 10) })}`; }
$('[name="collection"]', searchForm).addEventListener('input', updateExportLink); $('[name="as_of"]', searchForm).addEventListener('input', updateExportLink); updateExportLink();
searchForm.addEventListener('submit', async event => {
  event.preventDefault(); const submit = $('button[type="submit"]', searchForm); if (submit.disabled) return;
  const data = new FormData(searchForm), results = $('#search-results'); setBusy(submit, true, 'Đang tìm…'); results.replaceChildren(el('div', { class: 'loading' }, 'Đang tìm trong các nguồn đã được duyệt…'));
  try {
    const response = await api('/api/search', { method: 'POST', body: JSON.stringify({ query: String(data.get('query')).trim(), collection: String(data.get('collection')).trim(), as_of: data.get('as_of'), limit: 6 }) });
    results.replaceChildren(); const matches = response.results || [];
    if (!matches.length) results.append(el('div', { class: 'search-idle' }, el('span', { class: 'search-idle-icon', 'aria-hidden': 'true' }, '⌕'), el('h3', {}, 'Chưa có bằng chứng phù hợp'), el('p', {}, 'Thử từ khóa khác, kiểm tra bộ sưu tập và ngày áp dụng. Không suy đoán câu trả lời khi chưa có nguồn.')));
    else {
      results.append(el('div', { class: 'search-summary' }, el('strong', {}, `${matches.length} đoạn có thể đối chiếu`), el('span', {}, 'Chỉ từ tài liệu đã duyệt')));
      matches.forEach((match, index) => {
        const url = safeURL(match.source_url), open = button('Xem tài liệu đã duyệt ↗', async () => { if (await setView('library')) await selectDocument(match.document_id); }, '');
        results.append(el('article', { class: 'panel evidence-card' }, el('div', { class: 'evidence-top' }, el('span', { class: 'citation-index' }, `[${index + 1}]`), el('div', {}, el('h3', {}, match.title), el('small', {}, `${match.source_id} · Phiên bản ${match.document_version} · ${locationLabel(match.locator)}`))), el('blockquote', {}, match.text), el('div', { class: 'evidence-actions' }, open, url ? el('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, 'Mở nguồn web ↗') : el('span', {}, `Mã đoạn: ${match.chunk_id}`))));
      });
    }
  } catch (error) { results.replaceChildren(el('div', { class: 'notice error', role: 'alert' }, error.message)); }
  finally { setBusy(submit, false, 'Tìm trong kho →'); }
});
$('.brand').addEventListener('click', async event => { event.preventDefault(); if (!state.busy && await allowLeave()) { await setView('queue'); await closeDetail(); } });
async function boot() {
  try {
    state.config = await api('/api/config'); $('#open-ingest').disabled = false;
    const upstream = state.config.upstream || {}; $('#integration-dot').classList.toggle('green', Boolean(upstream.available)); $('#integration-dot').classList.toggle('amber', !upstream.available);
    $('#integration-state').textContent = upstream.available ? 'Đã kết nối scope-data-bot' : 'Bộ xử lý chưa sẵn sàng';
    $('#integration-info').textContent = upstream.available ? `Parser & chia đoạn local${upstream.commit ? ` · ${String(upstream.commit).slice(0, 7)}` : ''}` : 'Chưa thể tiếp nhận nguồn mới. Kiểm tra cấu hình bộ xử lý, rồi làm mới kết nối.';
    message(''); await refreshDocuments();
    if (location.hash === '#pipeline') { await setView('pipeline'); return; }
    if (location.hash === '#settings') { await setView('settings'); return; }
    const draft = readDraft(); if (!state.selected && !state.dirty && draft?.id && state.documents.some(doc => doc.id === draft.id && doc.status === 'pending' && doc.revision === draft.revision)) await selectDocument(draft.id);
  } catch (error) { $('#integration-state').textContent = 'Chưa kết nối máy chủ'; $('#integration-info').textContent = 'Làm mới danh sách để thử kết nối lại.'; message(error.message, true); $('#document-list').replaceChildren(el('div', { class: 'empty-state' }, el('h3', {}, 'Không thể kết nối'), el('p', {}, 'Máy chủ tài liệu chưa sẵn sàng.'), button('Thử lại', boot))); }
}
boot();
