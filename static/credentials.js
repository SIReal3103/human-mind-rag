export const keyStatusText = result => {
  const names = {ok:'Kiểm tra thành công', invalid_key:'Key bị từ chối', permission_denied:'Thiếu quyền API/model', quota_exceeded:'Hết hạn mức/billing', rate_limited:'Giới hạn lượt gọi/quota', network_error:'Lỗi mạng, chưa xác định key', capability_unverified:'BTC chưa kiểm thử khả năng', unsupported:'Chưa hỗ trợ kiểm tra', request_failed:'Yêu cầu thất bại', model_unavailable:'Model chưa khả dụng', invalid_request:'Sai tham số yêu cầu', invalid_output:'Nội dung model chưa đạt', not_tested:'Chưa kiểm tra'};
  return `${names[result?.status] || 'Chưa kiểm tra'}${result?.code ? ' · ' + result.code : ''}`;
};

// Key values remain in the password field only until submission; no browser storage.
export async function renderCredentials(container, api) {
  container.replaceChildren();
  let busy = false;
  const setBusy = value => {
    busy = value;
    container.querySelectorAll('button, input').forEach(control => { control.disabled = value; });
  };
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const notice = element('p', 'Đang đọc trạng thái cấu hình…', 'notice');
  notice.setAttribute('role', 'status');
  container.append(notice);
  try {
    const data = await api('/api/credentials');
    container.replaceChildren();
    container.append(element('p', 'Kho key này độc lập với pipeline API gốc. Crawl/build/evidence đọc environment hoặc scope-data-bot/.env.local; thay/reset key tại đây không thay key upstream.', 'notice'));
    container.append(element('p', 'BTC và các nhà cung cấp là hai bộ key độc lập. Nút Lưu/Thay key kiểm tra kết nối bằng cách liệt kê model, không sinh nội dung. Lỗi trong phiên cũ vẫn là lịch sử; cần chạy phiên mới sau khi thay key.', 'notice'));
    const storage = element('p', 'Key được lưu dạng file trên máy này, chỉ tài khoản hệ điều hành hiện tại được đọc/ghi (0600). File chưa mã hóa riêng; không lưu vào Git, tài liệu RAG hoặc bộ nhớ trình duyệt.', 'field-hint');
    container.append(storage, element('p', 'Kiểm tra key chỉ gọi API liệt kê model, không sinh nội dung. Thành công không đồng nghĩa đã có quyền dùng mọi model, tìm web, embedding hoặc Veo.', 'field-hint'));
    const health = element('section', '', 'panel credential-card'); health.setAttribute('aria-label','Trạng thái key hiện tại');
    health.append(element('h2', 'Trạng thái key hiện tại'));
    for (const provider of data.providers.filter(item => item.configured || item.id === 'btc')) {
      const result = provider.last_check;
      const row = element('div', '', result?.status === 'invalid_key' ? 'notice error' : 'notice');
      row.append(element('strong', `${provider.variable} · ${provider.configured ? keyStatusText(result) : 'Chưa có key'}`));
      if (result?.checked_at) row.append(element('p', `${result.stage_label} · ${new Date(result.checked_at).toLocaleString('vi-VN')}. ${result.message}`));
      health.append(row);
    }
    container.append(health);
    const resetArea = element('section', '', 'panel credential-card');
    const reset = element('button', 'Reset tất cả key', 'button danger'); reset.type = 'button';
    const confirmation = element('div'); confirmation.hidden = true;
    confirmation.id = 'credential-reset-confirmation';
    reset.setAttribute('aria-controls', confirmation.id);
    reset.setAttribute('aria-expanded', 'false');
    confirmation.append(element('p', 'Xóa toàn bộ key đã lưu: BTC, OpenAI, Google / Veo, Anthropic và DeepSeek? Tài liệu RAG được giữ nguyên. Sau đó bạn có thể nhập key BTC mới.', 'notice'));
    const actions = element('div', '', 'credential-actions');
    const cancel = element('button', 'Hủy', 'button'); cancel.type = 'button';
    const confirmReset = element('button', 'Xác nhận xóa tất cả key', 'button danger'); confirmReset.type = 'button';
    actions.append(cancel, confirmReset); confirmation.append(actions);
    const resetStatus = element('p', '', 'field-hint'); resetStatus.setAttribute('role', 'status');
    resetArea.append(reset, confirmation, resetStatus); container.append(resetArea);
    reset.addEventListener('click', () => {
      if (busy) return;
      confirmation.hidden = false; reset.setAttribute('aria-expanded', 'true'); cancel.focus();
    });
    cancel.addEventListener('click', () => {
      confirmation.hidden = true; reset.setAttribute('aria-expanded', 'false'); reset.focus();
    });
    confirmReset.addEventListener('click', async () => {
      if (busy) return;
      setBusy(true); resetStatus.textContent = 'Đang xóa tất cả key…';
      try {
        await api('/api/credentials/reset', {method:'POST',body:JSON.stringify({confirm:true})});
        container.querySelectorAll('input[type=password]').forEach(input => { input.value = ''; });
        await renderCredentials(container, api);
        const success = element('p', 'Đã xóa tất cả key đã lưu. Bạn có thể nhập key BTC mới bên dưới.', 'notice');
        success.setAttribute('role', 'status'); container.prepend(success);
        container.querySelector('#credential-btc')?.focus();
      } catch (error) { resetStatus.textContent = error.message; setBusy(false); }
    });
    for (const [group, title, explanation] of [
      ['btc', 'Gateway BTC', 'Dùng riêng key do Ban tổ chức cấp.'],
      ['external', 'Bộ key nhà cung cấp riêng', 'OpenAI, Google / Veo và các dịch vụ khác. Không tự fallback từ BTC sang bộ key này.'],
    ]) {
      const section = element('section', '', 'credential-group');
      section.append(element('h2', title), element('p', explanation, 'field-hint'));
      for (const provider of data.providers.filter(item => item.group === group)) {
        const form = element('form', '', 'panel credential-card');
        const heading = element('div', '', 'credential-heading');
        heading.append(element('h3', provider.name), element('span', provider.configured ? keyStatusText(provider.last_check) : 'Chưa có key', `badge ${provider.last_check?.status === 'ok' ? 'approved' : provider.last_check?.status === 'invalid_key' ? 'rejected' : 'neutral'}`));
        form.append(heading, element('p', provider.description, 'field-hint'));
        form.append(element('p', `Tên key: ${provider.variable}`, 'field-hint'));
        for (const check of Object.values(provider.checks || {}).sort((a,b) => b.checked_at.localeCompare(a.checked_at))) {
          form.append(element('p', `${check.stage_label}${check.model ? ' · ' + check.model : ''} · ${keyStatusText(check)} · ${new Date(check.checked_at).toLocaleString('vi-VN')}. ${check.message}`, check.status === 'ok' ? 'notice' : 'notice error'));
        }
        const label = element('label', provider.configured ? 'Nhập key mới để thay thế' : 'API key');
        const input = document.createElement('input');
        input.type = 'password'; input.name = 'api_key'; input.id = `credential-${provider.id}`;
        input.autocomplete = 'new-password'; input.spellcheck = false;
        input.required = true; input.minLength = 8; input.maxLength = 4096;
        input.placeholder = provider.configured ? 'Key đã lưu được giữ kín' : `Nhập ${provider.variable}`;
        label.append(input); form.append(label);
        const controls = element('div', '', 'credential-actions');
        const save = element('button', provider.configured ? 'Thay và kiểm tra key' : 'Lưu và kiểm tra key', 'button primary'); save.type = 'submit';
        controls.append(save);
        const status = element('p', '', 'field-hint'); status.setAttribute('role', 'status');
        if (provider.updated_at) form.append(element('small', `Lưu lúc ${new Date(provider.updated_at).toLocaleString('vi-VN')}`, 'field-hint'));
        if (provider.configured) {
          const check = element('button', 'Kiểm tra key', 'button'); check.type = 'button'; controls.append(check);
          check.addEventListener('click', async () => {
            if (busy) return;
            setBusy(true); status.textContent = `Đang kiểm tra ${provider.variable} tại ${provider.name}…`;
            try {
              const result = await api(`/api/credentials/${provider.id}/check`, {method:'POST',body:'{}'});
              await renderCredentials(container, api);
              if (!result.current) container.prepend(element('p', 'Key đã thay trong lúc kiểm tra. Kết quả cũ không áp dụng cho key mới.', 'notice'));
            } catch(error) { status.textContent = error.message; setBusy(false); }
          });
          const remove = element('button', 'Gỡ key', 'button danger'); remove.type = 'button';
          const confirm = document.createElement('input'); confirm.type = 'checkbox';
          const confirmation = element('label', '', 'check-label'); confirmation.append(confirm, document.createTextNode('Xác nhận gỡ key đã lưu'));
          controls.append(confirmation, remove);
          remove.addEventListener('click', async () => {
            if (busy) return;
            if (!confirm.checked) { status.textContent = 'Đánh dấu xác nhận trước khi gỡ key.'; return; }
            setBusy(true);
            try { await api(`/api/credentials/${provider.id}`, {method:'DELETE',body:'{}'}); await renderCredentials(container, api); }
            catch (error) { status.textContent = error.message; setBusy(false); }
          });
        }
        form.append(controls, status);
        form.addEventListener('submit', async event => {
          event.preventDefault(); if (busy) return;
          setBusy(true); status.textContent = 'Đang lưu key…';
          try {
            await api(`/api/credentials/${provider.id}`, {method:'PUT',body:JSON.stringify({api_key:input.value})});
            input.value = ''; status.textContent = 'Đã lưu. Đang kiểm tra key mới…';
            await api(`/api/credentials/${provider.id}/check`, {method:'POST',body:'{}'});
            await renderCredentials(container, api);
          } catch (error) { status.textContent = error.message; setBusy(false); }
          finally { input.value = ''; }
        });
        section.append(form);
      }
      container.append(section);
    }
  } catch (error) { notice.textContent = error.message; container.replaceChildren(notice); }
}
