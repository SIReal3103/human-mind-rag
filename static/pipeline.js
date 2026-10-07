import {keyStatusText} from './credentials.js';

export async function renderPipeline(container, api, openQueue, options = {}) {
  container.replaceChildren();
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text) node.textContent = text; if (cls) node.className = cls; return node; };
  const intro = el('p', 'Tìm nguồn → crawl → kiểm sơ bộ → người duyệt → embedding/index → evidence. Có thể bật tự động duyệt theo điều kiện; tài liệu chưa đạt vẫn chờ người duyệt. Điểm trích xuất không phải xác suất đúng.', 'notice');
  container.append(intro);
  const guide = el('ol', '', 'pipeline-guide');
  for (const [title, description] of [
    ['1. Tự tìm nguồn', 'Nhập chủ đề, địa bàn và giai đoạn. scope-data-bot dùng AI lập kế hoạch, tìm URL rồi crawl; cần key của provider đã chọn. Không phải nhập URL.'],
    ['2. Duyệt', 'Mở tài liệu của phiên, đối chiếu bản gốc, ghi người duyệt rồi phê duyệt hoặc từ chối.'],
    ['3. Tạo index', 'Chỉ bản đã duyệt còn hiệu lực được chia đoạn và gửi tới provider đã chọn để embedding. Cần key hợp lệ.'],
    ['4. Kiểm tra evidence', 'Đặt câu hỏi, đọc đoạn nguồn trả về và tải gói JSON cho agent. Đây là căn cứ để LLM trả lời, chưa phải câu trả lời.'],
  ]) {
    const item = el('li', '', 'panel'); item.append(el('strong', title), el('p', description)); guide.append(item);
  }
  container.append(guide);
  const toolbar = el('div', '', 'credential-actions');
  const fresh = el('button', '＋ Tạo phiên mới', 'button primary'); fresh.type = 'button';
  toolbar.append(fresh, el('p', 'Phiên mới bắt đầu bằng biểu mẫu trống. Các phiên trước được giữ trong Lịch sử.', 'field-hint')); container.append(toolbar);
  const form = el('form', '', 'panel credential-card');
  const formTitle = el('h2', 'Cấu hình phiên mới'); form.append(formTitle);
  const field = (name, title, value, type = 'text') => {
    const label = el('label', title), input = el(name === 'scope' ? 'textarea' : 'input'); input.name = name; if (input.tagName === 'INPUT') input.type = type; else input.rows = 3; input.value = value; input.required = true;
    label.append(input); form.append(label); return input;
  };
  const scope = field('scope', 'Phạm vi thu thập (nêu rõ chủ đề, địa bàn, giai đoạn)', ''); scope.minLength = 12; scope.maxLength = 8000; scope.placeholder = 'Ví dụ: Kinh tế, văn hóa Hà Nam giai đoạn 2020–2024';
  const collection = field('collection', 'Bộ tài liệu', ''); collection.maxLength = 100; collection.placeholder = 'Ví dụ: ha-nam';
  form.append(el('p', 'Tự tìm nguồn bằng scope-data-bot gốc: AI lập kế hoạch → tìm URL → crawl → parse/check. Không cần điền URL.', 'notice'));
  const pages = field('max_pages', 'Tối đa trang mỗi phiên (1–30)', '12', 'number'); pages.min = 1; pages.max = 30;
  const depth = field('max_depth', 'Độ sâu liên kết (0–2)', '1', 'number'); depth.min = 0; depth.max = 2;
  form.append(el('p', 'Mặc định repo: 12 trang, độ sâu 1, tối đa 5 nguồn đầu. Độ sâu 0 chỉ lấy trang tìm được; 1 theo thêm một lớp liên kết; 2 theo thêm hai lớp.', 'field-hint'));
  const apiConfigPanel = el('section', '', 'pipeline-api-choices');
  apiConfigPanel.setAttribute('aria-label', 'Cấu hình API gốc chỉ đọc');
  form.append(apiConfigPanel);
  let nativeConfig;
  const showConfig = config => {
    apiConfigPanel.replaceChildren(el('h3', 'API đang dùng · cấu hình scope-data-bot gốc'));
    apiConfigPanel.append(el('p', `Provider: ${config.provider}`, 'notice'));
    for (const [label, value] of [
      ['Lập kế hoạch / tìm nguồn / kiểm nội dung / rerank', config.text_model],
      ['Embedding tài liệu và câu hỏi', `${config.embedding_model} · ${config.dimensions} chiều`],
      ['Endpoint text và web search', config.endpoints.text_search],
      ['Endpoint embedding', config.endpoints.embedding],
      ['Nguồn cấu hình', config.precedence],
      ['Key', `${config.key.name} · ${config.key.configured ? 'Đã cấu hình (chưa xác nhận API gọi thành công)' : 'Chưa cấu hình'} · ${config.key.source}`],
    ]) apiConfigPanel.append(el('p', `${label}: ${value}`, 'field-hint'));
    if (config.provider === 'btc') {
      for (const [name, enabled] of Object.entries(config.capabilities)) apiConfigPanel.append(el('p', `${name}: ${enabled ? '1 · được cấu hình bật' : '0 · chưa bật; upstream sẽ kiểm gate'}`, enabled ? 'field-hint' : 'notice'));
    }
    apiConfigPanel.append(el('p', 'Chỉ hiển thị. Thay cấu hình bằng environment hoặc .env.local của checkout scope-data-bot rồi cập nhật trang. Key đã lưu trong mục Cấu hình API key của Human Mind không được dùng cho pipeline gốc. Không có adapter đổi model, prompt hoặc tự sửa assessment.', 'field-hint'));
  };
  const updateNativeConfig = async () => {
    nativeConfig = await api('/api/upstream/config'); showConfig(nativeConfig); return nativeConfig;
  };
  try { await updateNativeConfig(); } catch(error) { apiConfigPanel.append(el('p', error.message, 'notice error')); }
  const refreshConfig = el('button', 'Đọc lại cấu hình upstream', 'button'); refreshConfig.type = 'button';
  refreshConfig.addEventListener('click', async () => { try { await updateNativeConfig(); } catch(error) { apiConfigPanel.replaceChildren(el('p', error.message, 'notice error')); } });
  form.append(refreshConfig);
  const autoLabel = el('label', '', 'notice'), autoApprove = el('input'); autoApprove.type = 'checkbox'; autoApprove.id = 'pipeline-auto-approve';
  autoLabel.append(autoApprove, document.createTextNode(' Tự động duyệt tài liệu đủ điều kiện')); form.append(autoLabel);
  form.append(el('p', 'Tự duyệt chỉ áp dụng bản mới: điểm trích xuất ≥90, không cảnh báo/lỗi, có bằng chứng AI hợp lệ và khớp phạm vi. Bản không đạt giữ lại cho người duyệt. Lịch sử ghi rõ hệ thống duyệt; đây không phải xác minh sự thật.', 'field-hint'));
  const actions = el('div', '', 'credential-actions');
  const crawl = el('button', 'Bắt đầu crawl', 'button primary'); crawl.type = 'submit';
  const build = el('button', 'Tạo index từ bản đã duyệt', 'button'); build.type = 'button';
  const queue = el('button', 'Mở hàng chờ duyệt', 'button'); queue.type = 'button'; queue.addEventListener('click', async () => { try { await openQueue(); } catch(error) { status.textContent = error.message; } });
  actions.append(crawl, build, queue); form.append(actions);
  form.append(el('p', 'Bắt đầu crawl sẽ gọi AI để lập kế hoạch, tìm nguồn và kiểm nội dung, có thể phát sinh phí. Sau khi bản được duyệt thủ công hoặc tự động, Tạo index mới gửi nội dung để embedding. Lấy evidence dùng embedding, kiểm phạm vi và rerank theo repo gốc. Thu hồi/sửa nguồn làm index cũ bị chặn.', 'field-hint'));
  const status = el('p', '', 'field-hint'); status.setAttribute('role', 'status'); form.append(status); container.append(form);
  const prepare = job => {
    scope.value = job.scope; collection.value = job.collection;
    pages.value = job.max_pages || 12; depth.value = job.max_depth ?? 1;
    autoApprove.checked = job.auto_approve === true;
    formTitle.textContent = `Cấu hình từ phiên · ${job.collection}`;
  };
  if (options.preset) {
    prepare(options.preset);
    status.textContent = 'Bước 3: đã chọn bộ tài liệu vừa duyệt. Kiểm tra cấu hình API gốc đang hiển thị, rồi bấm Tạo index từ bản đã duyệt.';
  }
  const currentTitle = el('h2', 'Phiên đang xem', 'pipeline-jobs-title'); container.append(currentTitle);
  const jobs = el('section'); jobs.id = 'pipeline-current-job'; jobs.setAttribute('aria-label', 'Phiên đang xem'); container.append(jobs);
  const history = el('details', '', 'pipeline-history panel'), historyTitle = el('summary', 'Lịch sử các phiên'), historyList = el('div');
  history.append(historyTitle, historyList); container.append(history);
  const cards = new Map();
  const selectionKey = 'human-mind-pipeline-selection';
  let selectedId = options.preset?.id, initializeForm = !options.preset, loading = false, timer, running = false, reloadRequested = false, historySignature = '';
  if (selectedId === undefined) { try { const stored = sessionStorage.getItem(selectionKey); if (stored !== null) selectedId = stored || null; } catch { /* Selection still works without browser storage. */ } }
  const select = id => { selectedId = id; try { sessionStorage.setItem(selectionKey, id || ''); } catch { /* No credentials or document contents are stored here. */ } };
  if (options.preset) select(options.preset.id);
  const clearCard = () => { cards.clear(); jobs.replaceChildren(); };
  fresh.addEventListener('click', () => {
    select(null); clearCard(); history.open = false; scope.value = collection.value = '';
    pages.value = '12'; depth.value = '1'; autoApprove.checked = false;
    formTitle.textContent = 'Cấu hình phiên mới'; status.textContent = 'Nhập chủ đề và bộ tài liệu rồi bấm Bắt đầu crawl. API đọc cấu hình scope-data-bot; tài liệu cũ nằm trong Lịch sử.';
    load(); scope.focus(); form.scrollIntoView({behavior:'smooth',block:'start'});
  });
  const active = () => container.contains(form) && !container.hidden;
  const refresh = el('button', 'Cập nhật trạng thái', 'button'); refresh.type = 'button'; container.append(refresh);
  const names = {running:'Đang chạy', needs_review:'Đã nhập vào hàng chờ', no_documents:'Chưa có tài liệu nhập được', ready:'Index đã tạo', failed:'Không hoàn tất', interrupted:'Bị gián đoạn'};
  const nextStep = (job, documents) => {
    const section = el('section', '', 'pipeline-next-step');
    section.append(el('strong', 'Bước tiếp theo'));
    const pending = documents.filter(doc => doc.status === 'pending').length;
    const action = (label, callback) => {
      const control = el('button', label, 'button primary'); control.type = 'button';
      control.addEventListener('click', async () => {
        control.disabled = true;
        try { await callback(); } catch(error) { section.append(el('p', error.message, 'notice error')); }
        finally { control.disabled = false; }
      });
      section.append(control);
    };
    if (job.action === 'crawl' && job.document_ids.length) {
      section.append(el('p', pending ? `Đã tiếp nhận ${job.document_ids.length} tài liệu, còn ${pending} tài liệu chờ duyệt. Kiểm tra nguồn và nội dung trước khi đưa vào RAG.` : 'Phiên này không còn tài liệu chờ duyệt. Xem lại quyết định bên dưới; chỉ bản được phê duyệt mới có thể đưa vào index.'));
      action(pending ? `Tiếp tục duyệt ${pending} tài liệu →` : 'Xem tài liệu của phiên →', () => openQueue(job));
      if (pending) action('Tự động duyệt tài liệu đủ điều kiện', async () => { await api(`/api/pipeline/${job.id}/auto-review`, {method:'POST',body:'{}'}); await load(); });
      if (documents.some(doc => doc.status === 'approved')) action('Tiếp theo: cấu hình tạo index', () => { prepare(job); status.textContent = 'Đã chọn bộ tài liệu của phiên. Kiểm tra cấu hình upstream rồi bấm Tạo index từ bản đã duyệt; bước này có thể phát sinh phí.'; build.focus(); form.scrollIntoView({behavior:'smooth',block:'start'}); });
    } else if (job.status === 'running') {
      section.append(el('p', job.action === 'crawl' ? 'Đang thu thập. Khi có tài liệu, nút Tiếp tục duyệt sẽ xuất hiện ở đây. Trace tự cập nhật mỗi 3 giây.' : 'Đang tạo index. Khi hoàn tất, nhập câu hỏi để kiểm tra evidence.'));
    } else if (job.action === 'crawl') {
      section.classList.add('needs-attention');
      section.append(el('p', job.status === 'no_documents' ? 'Model đã trả kết quả nhưng chưa lấy được tài liệu để duyệt. Xem Trace chi tiết để biết nguồn bị chặn, lỗi HTTPS hoặc không khớp phạm vi. Đây không phải kết luận key hỏng.' : 'Chưa có tài liệu để duyệt. Xem bước lỗi trong trace và hướng dẫn xử lý, rồi chạy lại phiên.'));
      action('Xem cấu hình API upstream →', async () => { await updateNativeConfig(); apiConfigPanel.scrollIntoView({behavior:'smooth',block:'center'}); });
      action('Kiểm tra phạm vi và thử lại →', () => { prepare(job); status.textContent = 'Đã khôi phục phạm vi. Kiểm tra key trong environment hoặc scope-data-bot/.env.local rồi bấm Bắt đầu crawl; hệ thống sẽ tự tìm URL. Chưa chạy lại tự động.'; scope.focus(); form.scrollIntoView({behavior:'smooth',block:'start'}); });
    } else if (job.status === 'ready') {
      section.append(el('p', 'Index đã tạo. Nhập câu hỏi bên dưới và bấm Lấy evidence để kiểm tra nguồn trả về.'));
    } else {
      section.append(el('p', 'Index chưa sẵn sàng. Kiểm tra lỗi, key và tài liệu đã duyệt trước khi tạo lại.'));
      action('Xem cấu hình API upstream →', async () => { await updateNativeConfig(); apiConfigPanel.scrollIntoView({behavior:'smooth',block:'center'}); });
      action('Kiểm tra cấu hình tạo index →', () => { prepare(job); build.focus(); form.scrollIntoView({behavior:'smooth',block:'start'}); });
      if (options.openSearch) {
        section.append(el('p', 'Trong lúc chưa có index, có thể kiểm tra bản đã duyệt bằng tìm từ khóa local. Cách này không tạo embedding và không gọi AI.'));
        action('Tra cứu từ khóa không dùng key →', () => options.openSearch(job.collection));
      }
    }
    if (job.auto_review) {
      const outcomes = job.auto_review.outcomes;
      section.append(el('p', `Tự duyệt: ${outcomes.filter(o => o.status === 'approved' && o.approval_mode === 'automatic').length} đã duyệt tự động (${outcomes.filter(o => o.newly_approved).length} trong lượt này); ${outcomes.filter(o => o.status === 'approved' && o.approval_mode === 'manual').length} đã được người duyệt;  ${outcomes.filter(o => o.status === 'pending').length} giữ lại để kiểm tra.`));
      for (const outcome of outcomes.filter(o => o.reasons.length)) section.append(el('p', `${outcome.id.slice(0,8)}: ${outcome.reasons.join(' ')}`, 'field-hint'));
    }
    if (['failed','interrupted','no_documents'].includes(job.status)) action('Thử lại bước này với cấu hình đã chọn', async () => { prepare(job); await start(job.action); });
    return section;
  };
  const showTrace = async (job, panel) => {
    try {
      const trace = await api(`/api/pipeline/${job.id}/trace`);
      if (!active() || !panel.isConnected) return;
      const expanded = panel.querySelector('details[data-kind="lineage"]')?.open ?? job.status === 'running';
      panel.replaceChildren();
      panel.append(el('p', `Mã phiên: ${job.id}`, 'field-hint'));
      panel.append(el('p', trace.current ? `Đang thực hiện: ${trace.current.stage_label} · ${trace.current.label}` : (job.status === 'running' ? 'Đang chờ cập nhật bước xử lý…' : `Phiên đã kết thúc · ${trace.total_nodes || 0} bước được ghi nhận.`), 'trace-current'));
      if (trace.diagnosis) panel.append(el('p', `${trace.diagnosis.title}. ${trace.diagnosis.detail}`, 'notice error'));
      else if (trace.issues.length) panel.append(el('p', `${trace.issues.length} vấn đề nguồn/nội dung · ${trace.issues[0].stage}: ${trace.issues[0].message}. ${trace.issues[0].hint}`, 'notice error'));
      panel.append(el('p', trace.message, 'field-hint'));
      if (trace.api_calls?.length) {
        const calls = el('details'); calls.open = true; calls.append(el('summary', `API theo bước · ${trace.api_calls.length} lời gọi`));
        for (const call of trace.api_calls) calls.append(el('p', `${call.stage_label} · ${call.provider_name} · ${call.key_label} · ${call.model} · ${call.state === 'running' ? 'Đang gọi API' : call.state === 'success' ? 'API đã trả kết quả' : keyStatusText(call)}${call.validation === 'rejected' ? ' · Bằng chứng chưa đạt; xem lượt sửa tiếp theo hoặc chuyển duyệt' : call.validation === 'accepted' ? ' · ID/năm khớp đoạn trích; vẫn cần người duyệt' : ''}${call.current_key === false ? ' · key phiên cũ, đã thay/gỡ' : ''}${call.state === 'failed' ? '. ' + call.message : ''}`, call.state === 'failed' ? 'notice error' : 'field-hint'));
        panel.append(calls);
      }
      const details = el('details'); details.dataset.kind = 'lineage'; details.open = expanded;
      details.append(el('summary', `Trace chi tiết · ${trace.events.length} sự kiện`));
      for (const issue of trace.issues) details.append(el('p', `${issue.id} · ${issue.stage} · ${issue.code}: ${issue.message} — ${issue.hint}`, 'notice error'));
      if (job.crawl_summary) details.append(el('p', `Báo cáo upstream: ${job.crawl_summary}`, 'field-hint'));
      const list = el('ol', '', 'trace-events');
      const labels = {running:'Đang chạy',success:'Hoàn tất',failed:'Lỗi'};
      for (const event of trace.events) {
        const row = el('li', '', `trace-event trace-${event.status}`);
        const state = event.status === 'running' && job.status !== 'running' ? 'Chưa ghi nhận hoàn tất' : (labels[event.status] || event.status);
        row.append(el('strong', `${event.stage_label} · ${state}`), el('p', event.label));
        row.append(el('small', `${event.at ? new Date(event.at).toLocaleString('vi-VN') : '—'} · ${event.id}${event.parents?.length ? ' ← ' + event.parents.join(', ') : ''}`));
        if (event.url) row.append(el('p', `URL: ${event.url}`, 'trace-url'));
        if (event.path) row.append(el('p', `Tệp: ${event.path}`, 'field-hint'));
        if (event.issue_id) row.append(el('p', `Lỗi liên quan: ${event.issue_id}`, 'field-hint'));
        if (event.document_id) row.append(el('p', `Tài liệu: ${event.document_id} · ${event.document_status}`, 'field-hint'));
        list.append(row);
      }
      details.append(list); panel.append(details);
    } catch(error) { if (active()) panel.replaceChildren(el('p', `Không tải được trace: ${error.message}`, 'notice')); }
  };
  const showEvidence = (job, output, bundle) => {
    output.replaceChildren();
    const evidence = bundle.evidence || [];
    output.append(el('h4', evidence.length ? `Bước 4 · Đã lấy ${evidence.length} đoạn evidence` : 'Chưa tìm thấy evidence phù hợp'));
    output.append(el('p', evidence.length ? 'Đọc các đoạn và nguồn dưới đây trước khi đưa gói JSON cho agent. Đây là trích dẫn nguồn, chưa phải câu trả lời của LLM hay xác minh sự thật.' : 'Thử câu hỏi sát nội dung hơn hoặc bổ sung nguồn rồi duyệt và tạo lại index.', 'field-hint'));
    for (const chunk of evidence) {
      const item = el('article', '', 'pipeline-evidence-card');
      item.append(el('strong', chunk.title || 'Đoạn nguồn đã duyệt'), el('blockquote', chunk.text));
      const locator = chunk.locator || {};
      const location = [locator.page != null ? `Trang ${locator.page}` : '', Number.isInteger(locator.char_start) ? `ký tự ${locator.char_start}–${locator.char_end}` : ''].filter(Boolean).join(' · ');
      item.append(el('small', `Mã trích dẫn: ${chunk.id}${location ? ' · ' + location : ''}`));
      try {
        const url = new URL(chunk.source_url);
        if (['http:', 'https:'].includes(url.protocol)) { const link = el('a', 'Mở bài nguồn ↗', 'text-link'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; item.append(link); }
      } catch { /* Uploaded files need not have a public URL. */ }
      output.append(item);
    }
    const download = el('a', 'Tải evidence JSON cho agent', 'button');
    download.href = `/api/pipeline/${job.id}/evidence/download`;
    download.download = 'human-mind-evidence.json';
    output.append(download);
    const raw = el('details'), pre = el('pre', JSON.stringify(bundle, null, 2), 'pipeline-json'); raw.append(el('summary', 'Xem JSON và thông tin truy xuất'), pre);
    output.append(download, raw);
  };
  const savedEvidence = async (job, output, question) => {
    try {
      const result = await api(`/api/pipeline/${job.id}/evidence`);
      if (!active()) return;
      if (result.last_evidence) {
        if (!question.value) question.value = result.last_evidence.question;
        showEvidence(job, output, result.last_evidence.bundle);
        output.prepend(el('p', `Lần tra gần nhất: ${new Date(result.last_evidence.created_at).toLocaleString('vi-VN')} · ${result.last_evidence.question}`, 'field-hint'));
      }
    } catch (error) { if (active()) output.replaceChildren(el('p', error.message, 'notice error')); }
  };
  const load = async () => {
    if (!active()) return;
    if (loading) { reloadRequested = true; return; }
    loading = true; clearTimeout(timer);
    try {
      const [result, documentData] = await Promise.all([api('/api/pipeline'), api('/api/documents')]);
      if (!active()) return;
      running = result.jobs.some(job => job.status === 'running');
      refresh.textContent = running ? 'Đang tự cập nhật mỗi 3 giây · Cập nhật ngay' : 'Cập nhật trạng thái';
      if (selectedId === undefined) select(result.jobs[0]?.id || null);
      const visible = result.jobs.filter(job => job.id === selectedId);
      if (initializeForm) { if (visible[0] && !scope.value && !collection.value) prepare(visible[0]); initializeForm = false; }
      const older = result.jobs.filter(job => job.id !== selectedId);
      currentTitle.textContent = selectedId ? 'Phiên đang xem' : 'Phiên mới · chưa chạy';
      historyTitle.textContent = `Lịch sử · ${older.length} phiên khác`;
      const nextHistorySignature = JSON.stringify(older.map(job => [job.id, job.status, job.document_ids.length]));
      if (historySignature !== nextHistorySignature) {
        historySignature = nextHistorySignature; historyList.replaceChildren();
        for (const job of older) {
          const row = el('div', '', 'pipeline-history-row');
          row.append(el('strong', `${job.action === 'crawl' ? 'Crawl' : 'Index'} · ${job.collection}`), el('small', `${names[job.status] || job.status} · ${new Date(job.created_at).toLocaleString('vi-VN')} · ${job.id.slice(0, 8)}`));
          const open = el('button', `Mở phiên ${job.id.slice(0, 8)}`, 'button'); open.type = 'button';
          open.addEventListener('click', async () => { select(job.id); clearCard(); prepare(job); history.open = false; status.textContent = 'Đang xem lại phiên đã chọn. Bấm Bắt đầu crawl hoặc Tạo index sẽ tạo một phiên mới.'; await load(); currentTitle.scrollIntoView({behavior:'smooth',block:'start'}); });
          row.append(open); historyList.append(row);
        }
        if (!older.length) historyList.append(el('p', 'Chưa có phiên trước.', 'field-hint'));
      }
      if (!cards.size) jobs.replaceChildren();
      if (!visible.length) jobs.replaceChildren(el('p', selectedId ? 'Không tìm thấy phiên đã chọn. Mở một phiên trong Lịch sử hoặc tạo phiên mới.' : 'Chưa chạy phiên mới. Điền biểu mẫu bên trên để bắt đầu; kết quả sẽ xuất hiện tại đây.', 'notice'));
      for (const job of visible) {
        const previous = cards.get(job.id);
        const documents = documentData.documents.filter(doc => job.document_ids.includes(doc.id));
        const signature = JSON.stringify([job, documents.map(doc => [doc.id, doc.status, doc.revision])]);
        if (previous?.signature === signature) { if (previous.output) await savedEvidence(job, previous.output, previous.question); await showTrace(job, previous.panel); continue; }
        const card = el('article', '', 'panel credential-card');
        card.append(el('h3', `${job.action === 'crawl' ? 'Crawl' : 'Index'} · ${job.collection}`), el('p', `${names[job.status] || job.status} · ${new Date(job.created_at).toLocaleString('vi-VN')}`), el('p', job.scope));
        if (job.action === 'crawl') {
          card.append(el('p', `${job.document_ids.length} tài liệu đã tiếp nhận từ phiên này.`, 'field-hint'));
          card.append(el('p', job.integration === 'upstream-native-api' ? `scope-data-bot gốc · ${job.api_config.provider} · ${job.api_config.text_model} · ${job.upstream_commit.slice(0,7)}` : job.integration === 'upstream-model-routing' ? `scope-data-bot · ${job.key_group === 'btc' ? 'BTC' : 'Ngoài'} · model theo bước · ${job.upstream_commit.slice(0,7)}` : job.integration === 'upstream-stage-routing' ? `scope-data-bot · API theo từng bước · ${job.upstream_commit.slice(0,7)}` : job.integration === 'upstream-native' ? `scope-data-bot gốc · AI tự tìm nguồn · ${job.provider} · ${job.upstream_commit.slice(0, 7)}` : 'Phiên lịch sử dùng cách tích hợp cũ. Khi chạy lại, pipeline dùng AI tự tìm nguồn theo repo gốc.', 'field-hint'));
        }
        card.append(nextStep(job, documents));
        if (job.effective_scope && job.effective_scope !== job.scope) card.append(el('p', `Phạm vi đã quy đổi ngày ${job.scope_resolved_on}: ${job.effective_scope}`, 'notice'));
        if (job.error) { card.append(el('p', job.error, 'notice error')); card.append(el('p', 'Đây là kết quả của phiên đã chạy. Thay key không chạy lại phiên cũ; kiểm tra cấu hình upstream hiện tại ở trên rồi bấm Bắt đầu crawl để tạo lượt mới.', 'field-hint')); }
        for (const error of job.errors) card.append(el('p', error, 'notice error'));
        let output, question;
        if (job.status === 'ready') {
          card.append(el('p', `${job.manifest.chunk_count} đoạn · ${job.provider} · hiệu lực ${job.as_of}. Index sẽ được kiểm tra lại với quyết định duyệt khi truy vấn.`, 'field-hint'));
          question = el('input'); question.placeholder = 'Câu hỏi để lấy evidence'; question.maxLength = 8000; question.setAttribute('aria-label', 'Câu hỏi để lấy evidence');
          card.append(el('p', job.api_config ? `API gốc: ${job.api_config.provider} · ${job.api_config.text_model}. Embedding: ${job.model} · ${job.dimensions} chiều. Thay cấu hình cần tạo lại index.` : 'Index adapter cũ: xem evidence đã lưu hoặc tạo lại index bằng API gốc để tra mới.', 'notice'));
          const ask = el('button', 'Lấy evidence', 'button primary'); ask.type = 'button'; output = el('section', '', 'pipeline-evidence'); output.setAttribute('aria-live', 'polite');
          ask.disabled = job.integration !== 'upstream-native-api';
          ask.addEventListener('click', async () => {
            if (!question.value.trim()) { output.replaceChildren(el('p', 'Nhập câu hỏi trước khi lấy evidence.', 'notice error')); question.focus(); return; }
            ask.disabled = true; output.textContent = 'Đang truy hồi…';
            try { showEvidence(job, output, await api(`/api/pipeline/${job.id}/evidence`, {method:'POST',body:JSON.stringify({question:question.value})})); await showTrace(job, panel); }
            catch(error) { output.replaceChildren(el('p', error.message, 'notice error')); }
            finally { ask.disabled = false; }
          });
          card.append(question, ask, output);
        }
        const panel = el('section', '', 'pipeline-trace'); card.append(panel);
        if (previous) previous.card.replaceWith(card); else jobs.append(card);
        cards.set(job.id, {card, panel, signature, output, question});
        if (output) await savedEvidence(job, output, question);
        await showTrace(job, panel);
      }
    } catch(error) { if (active()) status.textContent = error.message; }
    finally { loading = false; if (active() && (running || reloadRequested)) timer = setTimeout(load, reloadRequested ? 0 : 3000); reloadRequested = false; }
  };
  const start = async action => {
    if (!form.reportValidity()) return;
    crawl.disabled = build.disabled = fresh.disabled = true;
    try {
      const config = await updateNativeConfig();
      if (!config.key.configured) throw new Error(`${config.key.name}: chưa có key trong environment hoặc scope-data-bot/.env.local. Chưa tạo phiên, chưa gọi AI.`);
      const job = await api('/api/pipeline', {method:'POST', body:JSON.stringify({action, scope:scope.value, collection:collection.value, max_pages:Number(pages.value), max_depth:Number(depth.value), auto_approve:action === 'crawl' && autoApprove.checked})});
      select(job.id); clearCard(); history.open = false;
      status.textContent = 'Đã bắt đầu. Trace tự cập nhật mỗi 3 giây khi phiên đang chạy. Có thể chuyển sang hàng chờ.'; await load();
      currentTitle.scrollIntoView({behavior:'smooth',block:'start'});
    } catch(error) { status.textContent = error.message; status.className = 'notice error'; status.scrollIntoView({behavior:'smooth',block:'center'}); }
    finally { crawl.disabled = build.disabled = fresh.disabled = false; }
  };
  form.addEventListener('submit', event => { event.preventDefault(); start('crawl'); }); build.addEventListener('click', () => start('build')); refresh.addEventListener('click', load);
  await load();
  if (options.preset) { build.focus(); form.scrollIntoView({behavior:'smooth',block:'start'}); }
}
