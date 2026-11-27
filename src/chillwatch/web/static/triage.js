/* 故障分诊交班台：拉取分诊结果、保存分诊单、模拟失败后从确认点恢复、幂等重跑。 */
(function () {
  'use strict';

  const root = document.getElementById('triage-desk');
  if (!root) return;

  const rowsBox = document.getElementById('triage-rows');
  const summaryBox = document.getElementById('triage-summary');
  const statusBox = document.getElementById('triage-ledger-status');
  const saveBtn = document.getElementById('triage-save');
  const failBtn = document.getElementById('triage-fail');
  const recoverBtn = document.getElementById('triage-recover');
  const rerunBtn = document.getElementById('triage-rerun');
  const resetBtn = document.getElementById('triage-reset');
  const navBtn = document.getElementById('nav-triage-desk');

  const LABELS = {
    unit: '机组', verdict: '去向', trade: '责任工种',
    pressure_brief: '压力线索', vibration_brief: '振动线索',
    basis_brief: '持续/历史', pending_reason: '裁定依据与未决原因',
  };
  const KEYS = ['unit', 'verdict', 'trade', 'pressure_brief', 'vibration_brief',
                'basis_brief', 'pending_reason'];

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function decisionClass(decision) {
    return 'badge-' + String(decision || '').toLowerCase();
  }

  function ticketMap(payload) {
    const map = new Map();
    (payload?.ledger?.tickets || []).forEach((ticket) => map.set(ticket.unit, ticket));
    return map;
  }

  function renderTable(payload) {
    const records = payload.records || [];
    const columns = payload.columns || LABELS;
    const keys = Object.keys(columns).length ? Object.keys(columns) : KEYS;
    const tickets = ticketMap(payload);

    const table = el('table', null, 'triage-table');
    const thead = table.createTHead().insertRow();
    keys.forEach((key) => thead.append(el('th', columns[key] || LABELS[key] || key)));
    thead.append(el('th', '分诊单/保存'));

    const body = table.createTBody();
    records.forEach((record) => {
      const tr = body.insertRow();
      tr.dataset.unit = record.unit;
      tr.dataset.decision = String(record.decision || '');
      keys.forEach((key) => {
        const td = tr.insertCell();
        if (key === 'verdict') {
          td.append(el('span', record.verdict || record.destination_label,
                       'badge ' + decisionClass(record.decision)));
        } else {
          const value = record[key];
          td.textContent = value === null || value === undefined || value === '' ? '—' : String(value);
          if (key === 'pending_reason' && record.pending === false) td.textContent = '—';
        }
      });
      const ticketCell = tr.insertCell();
      ticketCell.className = 'triage-ticket';
      const ticket = tickets.get(record.unit);
      if (!ticket) {
        ticketCell.append(el('span', '未建单', 'ticket ticket-none'));
      } else if (ticket.status === 'confirmed') {
        ticketCell.append(el('span', '已确认 ' + ticket.id, 'ticket ticket-ok'));
      } else if (ticket.status === 'failed') {
        ticketCell.append(el('span', '保存失败·待恢复', 'ticket ticket-fail'));
      } else {
        ticketCell.append(el('span', '待保存 ' + ticket.id, 'ticket ticket-pending'));
      }
    });
    rowsBox.replaceChildren(table);
  }

  function renderSummary(payload) {
    const ledger = payload.ledger || {};
    const chips = [
      `分诊机组 ${ledger.total ?? (payload.records || []).length}`,
      `已确认分诊单 ${ledger.confirmed ?? 0}`,
      `待处理 ${ledger.pending ?? 0}`,
      `失败 ${ledger.failed ?? 0}`,
      `重复单 ${ledger.duplicate ? '有' : '无'}`,
    ];
    if (ledger.checkpoint) chips.push(`确认点 ${ledger.checkpoint}`);
    summaryBox.replaceChildren(...chips.map((text) => el('span', text, 'chip')));
    recoverBtn.disabled = !(ledger.failed > 0 || (ledger.pending > 0 && ledger.confirmed >= 0 && payload.__failed));
  }

  function setStatus(message, isError) {
    statusBox.textContent = message;
    statusBox.classList.toggle('error', Boolean(isError));
  }

  function render(payload, message, isError) {
    if (!payload) return;
    renderTable(payload);
    renderSummary(payload);
    if (message) setStatus(message, isError);
    const ledger = payload.ledger || {};
    recoverBtn.disabled = !(ledger.failed > 0 || (isError && ledger.confirmed < ledger.total));
  }

  async function postJSON(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const payload = await response.json().catch(() => null);
    return { ok: response.ok, status: response.status, payload };
  }

  async function load() {
    try {
      const response = await fetch('/api/triage');
      if (!response.ok) throw new Error('分诊台读取失败');
      render(await response.json(), '分诊样例已载入');
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  saveBtn?.addEventListener('click', async () => {
    saveBtn.disabled = true;
    setStatus('正在保存分诊单…');
    const { ok, payload } = await postJSON('/api/triage/save', {});
    saveBtn.disabled = false;
    if (payload) {
      render(payload, ok ? `已保存 ${payload.ledger.confirmed} 张分诊单，无重复` : payload.message, !ok);
    } else {
      setStatus('保存请求失败', true);
    }
  });

  failBtn?.addEventListener('click', async () => {
    failBtn.disabled = true;
    setStatus('正在复现保存失败（在第 3 张单处中断）…');
    // 先重置，再让第 3 张（序号 2）写入失败：前两张形成“已确认分诊处”。
    const { payload } = await postJSON('/api/triage/save', { reset: true, fail_at: [2] });
    failBtn.disabled = false;
    if (payload) {
      payload.__failed = true;
      render(payload, `保存中断：已确认 ${payload.ledger.confirmed} 张，可从确认处恢复`, true);
    }
  });

  recoverBtn?.addEventListener('click', async () => {
    recoverBtn.disabled = true;
    setStatus('正从最后已确认分诊点恢复…');
    const { ok, payload } = await postJSON('/api/triage/recover', {});
    if (payload) render(payload, ok ? `恢复完成：${payload.ledger.confirmed} 张分诊单全部确认，未重复生单` : '恢复仍失败', !ok);
  });

  rerunBtn?.addEventListener('click', async () => {
    rerunBtn.disabled = true;
    const { payload } = await postJSON('/api/triage/rerun', {});
    rerunBtn.disabled = false;
    if (payload) render(payload, `重跑完成：共 ${payload.ledger.total} 张，重复=${payload.ledger.duplicate ? '是' : '否'}`);
  });

  resetBtn?.addEventListener('click', async () => {
    const { payload } = await postJSON('/api/triage/reset', {});
    if (payload) render(payload, '已重置为未保存的分诊计划');
  });

  navBtn?.addEventListener('click', () => {
    document.getElementById('triage-desk')?.scrollIntoView({ block: 'start' });
  });

  load();
})();
