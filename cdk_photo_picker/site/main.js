(() => {
  const logEl = document.getElementById('log');
  const btnSignIn = document.getElementById('btnSignIn');
  const btnPick = document.getElementById('btnPick');
  const btnPickLocal = document.getElementById('btnPickLocal');
  const btnUpload = document.getElementById('btnUpload');
  const selectedListEl = document.getElementById('selectedList');
  const btnRefreshUploads = document.getElementById('btnRefreshUploads');
  const btnLoadMoreUploads = document.getElementById('btnLoadMoreUploads');
  const uploadsContainerEl = document.getElementById('uploadsContainer');
  const uploadsListEl = document.getElementById('uploadsList');
  const uploadsEmptyEl = document.getElementById('uploadsEmpty');
  const refreshUploadsDefaultText = btnRefreshUploads?.textContent || '';
  if (btnRefreshUploads) btnRefreshUploads.disabled = true;
  const signinOverlay = document.getElementById('signinOverlay');
  const overlaySignIn = document.getElementById('overlaySignIn');
  const popupHintEl = document.getElementById('popupHint');
  const popupHintMessageEl = document.getElementById('popupHintMessage');
  const inputLocalFiles = document.getElementById('inputLocalFiles');

  const PENDING_SESSION_KEY = 'photopicker.pendingSession';
  const STORED_AUTH_STATE_KEY = 'photopicker.authState';
  const INITIAL_UPLOADS_VISIBLE = 5;
  const UPLOADS_PAGE_STEP = 10;
  const isLikelyMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent || '');
  const signInUxMode = isLikelyMobile ? 'redirect' : 'popup';
  const loginRedirectUri = `${window.location.origin}${window.location.pathname}`;
  let localItemSequence = 0;

  const state = {
    accessToken: null,
    accessTokenExpiresAt: 0,
    idToken: null,
    idTokenExpiresAt: 0,
    user: null,
    items: [], // { id, baseUrl, filename, mimeType, thumbUrl, downloadUrl, blob, status, progress }
    lastSessionId: null,
    lastPickerUri: null,
    uploads: [],
    uploadsVisibleCount: INITIAL_UPLOADS_VISIBLE,
    nextUploadsOffset: 0,
    uploadsHasMore: false,
    uploadsTotal: null,
    uploadsLoading: false,
    uploadsFetched: false,
    uploadsSelected: new Set(),
    signedIn: false,
    signInInProgress: false,
  };

  const cfg = window.AppConfig;
  if (!cfg) {
    appendLog('ERROR: config.js not found. Please copy site/config.example.js to site/config.js and fill values.');
  }

  renderUploadsList();

  function appendLog(msg, obj) {
    const time = new Date().toISOString();
    logEl.textContent += `[${time}] ${msg}\n`;
    if (obj) {
      try { logEl.textContent += JSON.stringify(obj, null, 2) + "\n"; } catch {}
    }
    logEl.scrollTop = logEl.scrollHeight;
  }

  function showPopupHint(message) {
    if (!popupHintEl) return;
    if (popupHintMessageEl && message) {
      popupHintMessageEl.textContent = message;
    }
    popupHintEl.classList.remove('hidden');
  }

  function hidePopupHint() {
    if (!popupHintEl) return;
    popupHintEl.classList.add('hidden');
  }

  function cleanupLocalItem(item) {
    if (item?.source === 'local' && item.localObjectUrl) {
      URL.revokeObjectURL(item.localObjectUrl);
      item.localObjectUrl = null;
    }
  }

  function refreshUploadButtonState() {
    if (!btnUpload) return;
    const hasPending = state.items.some((item) => !item.uploaded);
    btnUpload.disabled = !hasPending;
  }

  function createLocalItem(file) {
    const id = `local-${Date.now()}-${localItemSequence++}`;
    const objectUrl = URL.createObjectURL(file);
    return {
      id,
      source: 'local',
      baseUrl: '',
      filename: file.name || `${id}.jpg`,
      mimeType: file.type || 'application/octet-stream',
      size: file.size,
      thumbUrl: objectUrl,
      downloadUrl: objectUrl,
      localObjectUrl: objectUrl,
      blob: file,
      status: 'ready',
      progress: 0,
      uploaded: false,
    };
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return '-';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    const precision = value >= 10 || unitIndex === 0 ? 0 : 1;
    return `${value.toFixed(precision)} ${units[unitIndex]}`;
  }

  function formatDateTime(isoString) {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      if (Number.isNaN(date.getTime())) return isoString;
      return date.toLocaleString('ja-JP');
    } catch {
      return isoString;
    }
  }

  function getUploadTimestamp(item) {
    if (!item?.lastModified) return 0;
    const value = new Date(item.lastModified).getTime();
    return Number.isFinite(value) ? value : 0;
  }

  function sortUploadsDescending(items) {
    return Array.from(items).sort((a, b) => getUploadTimestamp(b) - getUploadTimestamp(a));
  }

  function mergeUploads(existing, incoming, { reset = false } = {}) {
    const map = new Map();
    if (!reset) {
      for (const item of existing) {
        if (item?.key) {
          map.set(item.key, item);
        }
      }
    }

    let freshCount = 0;
    for (const item of incoming) {
      if (!item?.key) continue;
      if (!map.has(item.key)) {
        freshCount += 1;
      }
      map.set(item.key, item);
    }

    return {
      uploads: sortUploadsDescending(map.values()),
      addedCount: reset ? incoming.length : freshCount,
    };
  }

  function setUploadsLoading(isLoading) {
    state.uploadsLoading = isLoading;
    if (btnRefreshUploads) {
      btnRefreshUploads.disabled = isLoading;
      if (isLoading) {
        btnRefreshUploads.textContent = '読込中…';
      } else {
        const fallback = refreshUploadsDefaultText || '一覧を表示';
        btnRefreshUploads.textContent = state.uploads.length ? '再読み込み' : fallback;
      }
    }
    if (btnLoadMoreUploads) {
      btnLoadMoreUploads.disabled = isLoading;
    }
    if (uploadsContainerEl) {
      uploadsContainerEl.classList.toggle('loading', isLoading);
    }
    if (uploadsEmptyEl && isLoading) {
      uploadsEmptyEl.textContent = '読み込み中…';
    }
  }

  function createUploadRow() {
    const row = document.createElement('div');
    row.className = 'upload-item';

    const selectCol = document.createElement('div');
    selectCol.className = 'upload-select-col';
    const selectLabel = document.createElement('label');
    selectLabel.className = 'upload-select-control';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'upload-select';
    selectLabel.appendChild(checkbox);
    selectCol.appendChild(selectLabel);
    row.appendChild(selectCol);

    const thumbImg = document.createElement('img');
    thumbImg.className = 'upload-thumb hidden';
    thumbImg.alt = '';
    row.appendChild(thumbImg);

    const thumbPlaceholder = document.createElement('div');
    thumbPlaceholder.className = 'upload-thumb';
    row.appendChild(thumbPlaceholder);

    const meta = document.createElement('div');
    meta.className = 'upload-meta';
    const title = document.createElement('strong');
    meta.appendChild(title);
    const detail = document.createElement('div');
    meta.appendChild(detail);
    const processedLine = document.createElement('div');
    processedLine.className = 'hidden';
    const processedTag = document.createElement('span');
    processedTag.className = 'tag';
    processedTag.textContent = 'processed';
    const processedText = document.createElement('span');
    processedLine.appendChild(processedTag);
    processedLine.appendChild(processedText);
    meta.appendChild(processedLine);
    row.appendChild(meta);

    const controls = document.createElement('div');
    controls.className = 'upload-controls';

    const previewLink = document.createElement('a');
    previewLink.classList.add('hidden');
    previewLink.target = '_blank';
    previewLink.rel = 'noopener';
    previewLink.textContent = 'プレビュー';
    controls.appendChild(previewLink);

    const rawLink = document.createElement('a');
    rawLink.classList.add('hidden');
    rawLink.target = '_blank';
    rawLink.rel = 'noopener';
    controls.appendChild(rawLink);

    row.appendChild(controls);
    row._els = {
      thumbImg,
      thumbPlaceholder,
      title,
      detail,
      processedLine,
      processedText,
      checkbox,
      previewLink,
      rawLink,
    };
    return row;
  }

  function updateUploadRow(row, item, index) {
    row.dataset.key = item.key;
    if (index < INITIAL_UPLOADS_VISIBLE) {
      row.classList.add('recent');
    } else {
      row.classList.remove('recent');
    }
    const {
      thumbImg,
      thumbPlaceholder,
      title,
      detail,
      processedLine,
      processedText,
      checkbox,
      previewLink,
      rawLink,
    } = row._els || {};

    const previewUrl = item.processedUrl || item.downloadUrl || '';
    if (thumbImg && thumbPlaceholder) {
      if (previewUrl) {
        thumbPlaceholder.classList.add('hidden');
        thumbImg.classList.remove('hidden');
        if (thumbImg.getAttribute('src') !== previewUrl) {
          thumbImg.src = previewUrl;
        }
        thumbImg.alt = item.key;
      } else {
        thumbImg.classList.add('hidden');
        thumbImg.removeAttribute('src');
        thumbPlaceholder.classList.remove('hidden');
      }
    }

    if (title) title.textContent = item.key;
    if (detail) {
      const formattedSize = formatBytes(Number(item.size || 0));
      const formattedDate = formatDateTime(item.lastModified);
      detail.textContent = `サイズ: ${formattedSize} / 更新: ${formattedDate || '-'}`;
    }

    if (processedLine && processedText) {
      if (item.processedKey) {
        processedLine.classList.remove('hidden');
        processedText.textContent = item.processedKey;
      } else {
        processedLine.classList.add('hidden');
        processedText.textContent = '';
      }
    }

    if (checkbox) {
      checkbox.dataset.key = item.key;
      checkbox.checked = state.uploadsSelected.has(item.key);
    }

    if (previewLink) {
      if (previewUrl) {
        previewLink.classList.remove('hidden');
        previewLink.href = previewUrl;
      } else {
        previewLink.classList.add('hidden');
        previewLink.removeAttribute('href');
      }
    }

    if (rawLink) {
      if (item.processedUrl && item.downloadUrl && item.processedUrl !== item.downloadUrl) {
        rawLink.classList.remove('hidden');
        rawLink.href = item.downloadUrl;
        rawLink.textContent = '元画像';
      } else if (!previewUrl && item.downloadUrl) {
        rawLink.classList.remove('hidden');
        rawLink.href = item.downloadUrl;
        rawLink.textContent = '開く';
      } else {
        rawLink.classList.add('hidden');
        rawLink.removeAttribute('href');
        rawLink.textContent = '';
      }
    }
  }

  function renderUploadsList() {
    if (!uploadsContainerEl || !uploadsListEl) return;
    const totalUploads = state.uploads.length;
    let visibleCount = state.uploadsVisibleCount || INITIAL_UPLOADS_VISIBLE;
    visibleCount = Math.min(visibleCount, totalUploads);
    state.uploadsVisibleCount = visibleCount;
    if (!totalUploads) {
      uploadsListEl.innerHTML = '';
      uploadsContainerEl.classList.add('empty');
      if (uploadsEmptyEl) {
        if (state.uploadsLoading) {
          uploadsEmptyEl.textContent = '読み込み中…';
        } else if (state.uploadsFetched) {
          uploadsEmptyEl.textContent = 'アップロードはありません。';
        }
      }
      if (btnLoadMoreUploads) {
        btnLoadMoreUploads.classList.add('hidden');
      }
      return;
    }
    uploadsContainerEl.classList.remove('empty');
    if (uploadsEmptyEl) uploadsEmptyEl.textContent = '';

    const slice = state.uploads.slice(0, visibleCount);

    const existingRows = new Map();
    Array.from(uploadsListEl.children).forEach((child) => {
      if (child instanceof HTMLElement && child.dataset.key) {
        existingRows.set(child.dataset.key, child);
      }
    });

    slice.forEach((item, index) => {
      let row = existingRows.get(item.key);
      if (!row) {
        row = createUploadRow();
      }
      updateUploadRow(row, item, index);
      existingRows.delete(item.key);
      const currentChild = uploadsListEl.children[index];
      if (currentChild !== row) {
        uploadsListEl.insertBefore(row, currentChild || null);
      }
    });

    // remove extra rows beyond current slice
    while (uploadsListEl.children.length > slice.length) {
      uploadsListEl.removeChild(uploadsListEl.lastElementChild);
    }
    existingRows.forEach((row) => {
      if (row.parentElement === uploadsListEl) {
        uploadsListEl.removeChild(row);
      }
    });

    if (btnLoadMoreUploads) {
      const totalKnown = typeof state.uploadsTotal === 'number' ? state.uploadsTotal : null;
      const remainingLocal = Math.max(0, totalUploads - visibleCount);
      const remainingTotal = totalKnown !== null ? Math.max(0, totalKnown - visibleCount) : null;
      const hasHiddenLocal = remainingLocal > 0;
      const canFetchMore = state.uploadsHasMore || (remainingTotal !== null && remainingTotal > 0);
      if (hasHiddenLocal || canFetchMore) {
        btnLoadMoreUploads.classList.remove('hidden');
        btnLoadMoreUploads.disabled = state.uploadsLoading && !hasHiddenLocal;
        const remainingDisplay = hasHiddenLocal
          ? remainingLocal
          : (remainingTotal !== null ? remainingTotal : null);
        if (remainingDisplay !== null && remainingDisplay > 0) {
          btnLoadMoreUploads.textContent = `さらに表示（残り ${remainingDisplay} 件）`;
        } else {
          btnLoadMoreUploads.textContent = 'さらに表示';
        }
      } else {
        btnLoadMoreUploads.classList.add('hidden');
      }
    }

    updateBulkDeleteVisibility();
  }

  function updateBulkDeleteVisibility() {
    const bulkDeleteBtn = document.getElementById('btnDeleteSelected');
    const hasSelection = state.uploadsSelected.size > 0;
    if (bulkDeleteBtn) {
      bulkDeleteBtn.disabled = !hasSelection;
    }
  }

  function toggleUploadSelection(key, selected) {
    if (!key) return;
    if (selected) {
      state.uploadsSelected.add(key);
    } else {
      state.uploadsSelected.delete(key);
    }
    updateBulkDeleteVisibility();
  }

  function applySignedInState() {
    if (!state.signedIn) {
      state.signedIn = true;
      appendLog('サインイン完了。写真を選択できます。');
    } else {
      appendLog('再サインインが完了しました。');
    }
    if (btnPick) btnPick.disabled = false;
    if (btnPickLocal) btnPickLocal.disabled = false;
    if (btnSignIn) {
      btnSignIn.textContent = 'Google サインイン済み';
      btnSignIn.dataset.locked = 'true';
      btnSignIn.disabled = true;
      btnSignIn.classList.add('solid');
    }
    if (btnRefreshUploads) btnRefreshUploads.disabled = false;
    hideSigninOverlay();
    hidePopupHint();
    refreshUploadButtonState();
  }

  function showSigninOverlay() {
    signinOverlay?.classList.remove('hidden');
  }

  function hideSigninOverlay() {
    signinOverlay?.classList.add('hidden');
  }

  async function completeSignIn(forcePrompt = false, options = {}) {
    if (state.signInInProgress) return;
    state.signInInProgress = true;
    const { auto = false, silent = false } = options;
    if (!auto) {
      btnSignIn?.setAttribute('disabled', 'disabled');
      overlaySignIn?.setAttribute('disabled', 'disabled');
    }
    try {
      await ensureIdTokenInteractive(forcePrompt, { allowPrompt: true });
      applySignedInState();
      if (cfg?.upload?.manageEndpoint) {
        await fetchUploadsList({ resetVisible: true, offset: 0, limit: INITIAL_UPLOADS_VISIBLE });
      }
    } catch (err) {
      const prefix = auto ? 'WARN' : 'ERROR';
      const action = auto ? '自動サインイン' : 'サインイン';
      if (!silent) appendLog(`${prefix}: ${action}に失敗しました: ${err.message}`);
    } finally {
      state.signInInProgress = false;
      if (btnSignIn && btnSignIn.dataset.locked !== 'true') {
        btnSignIn.removeAttribute('disabled');
      }
      overlaySignIn?.removeAttribute('disabled');
    }
  }

  async function fetchUploadsList({ resetVisible = false, offset = 0, limit = INITIAL_UPLOADS_VISIBLE } = {}) {
    if (!cfg?.upload?.manageEndpoint) {
      appendLog('WARN: upload.manageEndpoint is not configured in config.js');
      return;
    }
    try {
      await ensureIdTokenInteractive(false, { allowPrompt: true });
    } catch (err) {
      appendLog(`ERROR: アップロード一覧の取得には Google サインインが必要です: ${err.message}`);
      return;
    }
    setUploadsLoading(true);
    try {
      const url = new URL(cfg.upload.manageEndpoint);
      const safeLimit = Math.max(1, limit);
      const safeOffset = Math.max(0, offset);
      url.searchParams.set('limit', String(safeLimit));
      url.searchParams.set('offset', String(safeOffset));

      const resp = await fetch(url.toString(), {
        headers: {
          Authorization: `Bearer ${state.idToken}`,
        },
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => '');
        throw new Error(`status ${resp.status}${text ? ` ${text}` : ''}`);
      }
      const data = await resp.json();
      const incoming = Array.isArray(data.items) ? data.items : [];
      const totalFromApi = typeof data.total === 'number' ? data.total : undefined;

      const previousVisible = state.uploadsVisibleCount || 0;
      const baselineVisible = previousVisible || INITIAL_UPLOADS_VISIBLE;
      const resetting = resetVisible || safeOffset === 0;
      const { uploads: mergedUploads, addedCount } = mergeUploads(state.uploads, incoming, { reset: resetting });
      state.uploads = mergedUploads;
      if (resetting) {
        const desiredVisible = resetVisible
          ? Math.max(INITIAL_UPLOADS_VISIBLE, Math.min(baselineVisible, mergedUploads.length))
          : Math.max(baselineVisible, INITIAL_UPLOADS_VISIBLE);
        state.uploadsVisibleCount = Math.min(mergedUploads.length, desiredVisible);
      } else {
        state.uploadsVisibleCount = Math.min(
          mergedUploads.length,
          baselineVisible + addedCount
        );
      }

      state.uploadsFetched = true;
      const validKeys = new Set(state.uploads.map((item) => item.key));
      state.uploadsSelected = new Set(
        Array.from(state.uploadsSelected).filter((key) => validKeys.has(key))
      );

      const defaultNext = safeOffset + incoming.length;
      const providedNext = data.nextOffset !== undefined && data.nextOffset !== null
        ? Number(data.nextOffset)
        : undefined;
      const computedNext = Number.isFinite(providedNext) ? providedNext : defaultNext;
      state.nextUploadsOffset = Number.isFinite(computedNext)
        ? Math.max(safeOffset + incoming.length, computedNext)
        : safeOffset + incoming.length;
      if (typeof state.uploadsTotal === 'number') {
        state.nextUploadsOffset = Math.min(state.nextUploadsOffset, state.uploadsTotal);
      }

      let serverHasMore;
      if (typeof data.hasMore === 'boolean') {
        serverHasMore = data.hasMore;
      } else {
        serverHasMore = incoming.length === safeLimit && incoming.length > 0;
        if (serverHasMore && totalFromApi !== undefined) {
          serverHasMore = computedNext < totalFromApi;
        }
      }
      if (serverHasMore && safeOffset > 0 && addedCount === 0) {
        serverHasMore = false;
      }
      const nextTotal = totalFromApi !== undefined
        ? totalFromApi
        : (!serverHasMore ? state.uploads.length : state.uploadsTotal);
      if (typeof nextTotal === 'number') {
        state.uploadsTotal = nextTotal;
      }
      const moreByTotal = typeof state.uploadsTotal === 'number'
        ? state.uploads.length < state.uploadsTotal
        : false;
      state.uploadsHasMore = Boolean(serverHasMore) || moreByTotal;
      renderUploadsList();
      const visibleNow = state.uploadsVisibleCount || 0;
      const totalKnownCount = typeof state.uploadsTotal === 'number'
        ? state.uploadsTotal
        : state.uploads.length;
      appendLog(`アップロード一覧を取得しました（全 ${totalKnownCount} 件中 ${visibleNow} 件を表示）`);
      const newlyVisible = Math.max(0, visibleNow - previousVisible);
      if (!resetting && newlyVisible > 0) {
        appendLog(`INFO: 新たに ${newlyVisible} 件を表示しました（合計 ${visibleNow} 件）`);
      }
    } catch (err) {
      appendLog(`ERROR: アップロード一覧の取得に失敗しました: ${err.message}`);
      if (uploadsEmptyEl) {
        uploadsEmptyEl.textContent = '取得に失敗しました。時間をおいて再度お試しください。';
      }
    } finally {
      setUploadsLoading(false);
      renderUploadsList();
      updateBulkDeleteVisibility();
    }
  }

  async function deleteUpload(key) {
    if (!cfg?.upload?.manageEndpoint) {
      throw new Error('manageEndpoint is not configured');
    }
    await ensureIdTokenInteractive(false, { allowPrompt: true });
    const resp = await fetch(cfg.upload.manageEndpoint, {
      method: 'DELETE',
      headers: {
        'content-type': 'application/json',
        Authorization: `Bearer ${state.idToken}`,
      },
      body: JSON.stringify({ key }),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      throw new Error(`status ${resp.status}${text ? ` ${text}` : ''}`);
    }
    const data = await resp.json();
    state.uploads = state.uploads.filter((item) => item.key !== key);
    state.uploadsSelected.delete(key);
    renderUploadsList();
    updateBulkDeleteVisibility();
    return data;
  }

  function buildMediaUrl(baseUrl, variant) {
    if (!baseUrl) return '';
    const variantPart = variant ? `=${variant}` : '';
    const tokenQuery = state.accessToken ? `?access_token=${encodeURIComponent(state.accessToken)}` : '';
    return `${baseUrl}${variantPart}${tokenQuery}`;
  }

  function refreshAllMediaUrls() {
    for (const item of state.items) {
      if (item.source === 'local') {
        if (item.localObjectUrl) {
          item.thumbUrl = item.localObjectUrl;
          item.downloadUrl = item.localObjectUrl;
          if (item._els?.img) {
            item._els.img.src = item.localObjectUrl;
          }
        }
        continue;
      }
      item.thumbUrl = buildMediaUrl(item.baseUrl, 'w400-h400-c');
      item.downloadUrl = buildMediaUrl(item.baseUrl, 'd');
      if (item._els?.img && item.thumbUrl) {
        item._els.img.src = item.thumbUrl;
      }
    }
  }

  function decodeJwtPayload(jwt) {
    try {
      const payload = jwt.split('.')[1];
      const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
      try { return JSON.parse(decodeURIComponent(escape(json))); } catch { return JSON.parse(json); }
    } catch { return {}; }
  }

  let gisInitialized = false;
  let pendingIdResolve = null;
  let pendingIdReject = null;
  let accessTokenInFlight = null;
  let tokenClient = null;
  let autoPromptAttempted = false;
  let autoPromptHandled = false;

  async function initGsi() {
    if (gisInitialized) return;
    await waitForGis();
    const clientId = cfg?.google?.clientId;
    if (!clientId) {
      appendLog('WARN: google.clientId not set; Google Sign-In disabled');
      return;
    }
    const initOptions = {
      client_id: clientId,
      callback: (resp) => {
        if (resp && resp.credential) {
          state.idToken = resp.credential;
          const payload = decodeJwtPayload(resp.credential);
          state.user = { sub: payload.sub, email: payload.email, name: payload.name, picture: payload.picture };
          state.idTokenExpiresAt = payload?.exp ? payload.exp * 1000 : Date.now() + 55 * 60 * 1000;
          const ui = document.getElementById('userInfo');
          if (ui) ui.textContent = state.user?.email ? `ログイン中: ${state.user.email}` : 'ログイン済み';
          appendLog('Google ID token acquired');
          persistAuthState();
          const hadPending = Boolean(pendingIdResolve);
          if (pendingIdResolve) pendingIdResolve(resp.credential);
          if (!hadPending) {
            if (!state.signedIn) {
              completeSignIn(false, { auto: true, silent: true }).catch((err) => {
                appendLog(`WARN: 自動サインインに失敗しました: ${err.message}`);
              });
            } else {
              hideSigninOverlay();
            }
          }
        } else if (pendingIdReject) {
          pendingIdReject(new Error('Google サインインに失敗しました'));
        }
        pendingIdResolve = pendingIdReject = null;
      },
      auto_select: true,
      ux_mode: signInUxMode,
      cancel_on_tap_outside: false,
      itp_support: true,
      use_fedcm_for_prompt: true,
    };
    if (signInUxMode === 'redirect') {
      initOptions.login_uri = loginRedirectUri;
    }
    google.accounts.id.initialize(initOptions);
    if (!autoPromptAttempted && !state.signedIn) {
      autoPromptAttempted = true;
      try {
        google.accounts.id.prompt((notification) => {
          autoPromptHandled = true;
          if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
            const reason = notification.getNotDisplayedReason?.() || notification.getSkippedReason?.();
            appendLog(`INFO: 自動サインインはスキップされました${reason ? ` (${reason})` : ''}`);
            if (!state.signedIn) {
              showSigninOverlay();
              if (isLikelyMobile) {
                appendLog('INFO: 最初に「Google にサインイン」をタップして認証してください。');
              } else {
                appendLog('INFO: まず「Google にサインイン」をクリックして認証してください。');
              }
            }
          } else if (notification.isDismissedMoment()) {
            const reason = notification.getDismissedReason?.();
            appendLog(`INFO: Google サインインがキャンセルされました${reason ? ` (${reason})` : ''}`);
            if (!state.signedIn) {
              showSigninOverlay();
              if (isLikelyMobile) {
                appendLog('INFO: 最初に「Google にサインイン」をタップして認証してください。');
              } else {
                appendLog('INFO: まず「Google にサインイン」をクリックして認証してください。');
              }
            }
          }
        });
        setTimeout(() => {
          if (!state.signedIn && !autoPromptHandled) {
            showSigninOverlay();
            if (isLikelyMobile) {
              appendLog('INFO: 最初に「Google にサインイン」をタップして認証してください。');
            } else {
              appendLog('INFO: まず「Google にサインイン」をクリックして認証してください。');
            }
          }
        }, 1500);
      } catch (err) {
        appendLog(`WARN: 自動サインインの初期化に失敗しました: ${err.message}`);
      }
    }
    gisInitialized = true;
  }

  function waitForGis() {
    return new Promise((resolve) => {
      const check = () => {
        if (window.google?.accounts?.id && window.google?.accounts?.oauth2) {
          resolve();
        } else {
          setTimeout(check, 50);
        }
      };
      check();
    });
  }

  function loadPendingSession() {
    const raw = sessionStorage.getItem(PENDING_SESSION_KEY);
    if (!raw) return null;
    try {
      const data = JSON.parse(raw);
      if (!data?.sessionId) return null;
      const maxAgeMs = 10 * 60 * 1000;
      if (data.createdAt && (Date.now() - data.createdAt) > maxAgeMs) {
        sessionStorage.removeItem(PENDING_SESSION_KEY);
        return null;
      }
      return data;
    } catch {
      sessionStorage.removeItem(PENDING_SESSION_KEY);
      return null;
    }
  }

  function savePendingSession(sessionId) {
    sessionStorage.setItem(PENDING_SESSION_KEY, JSON.stringify({ sessionId, createdAt: Date.now() }));
  }

  function clearPendingSession() {
    sessionStorage.removeItem(PENDING_SESSION_KEY);
  }

  function persistAuthState() {
    if (state.idToken && state.idTokenExpiresAt) {
      const payload = {
        idToken: state.idToken,
        idTokenExpiresAt: state.idTokenExpiresAt,
        user: state.user,
      };
      try {
        sessionStorage.setItem(STORED_AUTH_STATE_KEY, JSON.stringify(payload));
      } catch (err) {
        appendLog(`WARN: 認証状態の保存に失敗しました: ${err.message}`);
      }
    } else {
      sessionStorage.removeItem(STORED_AUTH_STATE_KEY);
    }
  }

  function restoreAuthState() {
    const raw = sessionStorage.getItem(STORED_AUTH_STATE_KEY);
    if (!raw) return false;
    try {
      const data = JSON.parse(raw);
      if (!data?.idToken || !data?.idTokenExpiresAt) {
        sessionStorage.removeItem(STORED_AUTH_STATE_KEY);
        return false;
      }
      if (!isFresh(data.idTokenExpiresAt)) {
        sessionStorage.removeItem(STORED_AUTH_STATE_KEY);
        return false;
      }
      state.idToken = data.idToken;
      state.idTokenExpiresAt = data.idTokenExpiresAt;
      state.user = data.user || null;
      appendLog('INFO: 保存されたサインイン状態を復元しました。');
      applySignedInState();
      if (cfg?.upload?.manageEndpoint) {
        fetchUploadsList({ resetVisible: true, offset: 0, limit: INITIAL_UPLOADS_VISIBLE });
      }
      return true;
    } catch {
      sessionStorage.removeItem(STORED_AUTH_STATE_KEY);
      return false;
    }
  }

  function isFresh(expiry) {
    return expiry && Date.now() < (expiry - 60 * 1000);
  }

  function ensureIdTokenInteractive(forcePrompt = false, { allowPrompt = false } = {}) {
    if (!forcePrompt && state.idToken && isFresh(state.idTokenExpiresAt)) {
      return Promise.resolve(state.idToken);
    }
    return new Promise(async (resolve, reject) => {
      await initGsi();
      if (!window.google?.accounts?.id) {
        reject(new Error('Google Identity Services が読み込まれていません'));
        return;
      }
      const shouldPrompt = forcePrompt || allowPrompt;
      if (!shouldPrompt) {
        reject(new Error('Google サインインが必要です'));
        return;
      }
      pendingIdResolve = (token) => {
        pendingIdResolve = pendingIdReject = null;
        resolve(token);
      };
      pendingIdReject = (err) => {
        pendingIdResolve = pendingIdReject = null;
        reject(err);
      };
      google.accounts.id.prompt((notification) => {
        if (notification.isDismissedMoment()) {
          const dismissedReason = notification.getDismissedReason?.();
          if (dismissedReason === 'credential_returned' || dismissedReason === 'credential_returned_for_second_factor') {
            return;
          }
        }
        if (notification.isNotDisplayed() || notification.isSkippedMoment() || notification.isDismissedMoment()) {
          if (pendingIdReject) {
            const dismissedReason = notification.getDismissedReason?.();
            pendingIdReject(
              new Error(
                dismissedReason
                  ? `Google サインインがキャンセルされました (${dismissedReason})`
                  : 'Google サインインがキャンセルされました'
              ),
            );
          }
        }
      });
    });
  }

  function ensureAccessTokenInteractive(forceConsent = false) {
    if (!forceConsent && state.accessToken && isFresh(state.accessTokenExpiresAt)) {
      return Promise.resolve(state.accessToken);
    }
    if (accessTokenInFlight) return accessTokenInFlight;

    const scopes = (cfg?.google?.scopes || []).join(' ');
    accessTokenInFlight = new Promise(async (resolve, reject) => {
      try {
        await initGsi();
        if (!window.google?.accounts?.oauth2) {
          throw new Error('Google OAuth クライアントが利用できません');
        }
        if (!tokenClient) {
          tokenClient = window.google.accounts.oauth2.initTokenClient({
            client_id: cfg?.google?.clientId,
            scope: scopes,
            include_granted_scopes: true,
            prompt: '',
            callback: () => {},
          });
        }
        tokenClient.callback = (resp) => {
          accessTokenInFlight = null;
          if (resp?.error) {
            reject(new Error(resp.error));
            return;
          }
          if (!resp?.access_token) {
            reject(new Error('No access token in response'));
            return;
          }
          state.accessToken = resp.access_token;
          const expiresIn = Number(resp.expires_in || 3600);
          state.accessTokenExpiresAt = Date.now() + expiresIn * 1000;
          appendLog('Picker API access token acquired');
          refreshAllMediaUrls();
          resolve(resp.access_token);
        };
        tokenClient.requestAccessToken({
          prompt: forceConsent ? 'consent' : '',
          scope: scopes,
          login_hint: state.user?.email,
        });
      } catch (err) {
        accessTokenInFlight = null;
        reject(err);
      }
    });
    return accessTokenInFlight;
  }

  function parseDurationToMs(durationStr, fallbackMs) {
    if (!durationStr) return fallbackMs;
    const match = durationStr.match(/^(\d+)(?:\.(\d+))?s$/);
    if (!match) return fallbackMs;
    const seconds = Number(match[1] || 0);
    const fraction = Number(`0.${match[2] || ''}`);
    return Math.round((seconds + fraction) * 1000);
  }

  async function createPickerSession(accessToken) {
    const body = {
      pickingConfig: {
        maxItemCount: 200,
      },
    };
    const doCreate = async (token) => fetch('https://photospicker.googleapis.com/v1/sessions', {
      method: 'POST',
      headers: {
        'authorization': `Bearer ${token}`,
        'content-type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    let resp = await doCreate(accessToken);
    if (resp.status === 401) {
      const refreshed = await ensureAccessTokenInteractive(true);
      resp = await doCreate(refreshed);
    }
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`sessions.create failed: ${resp.status} ${text}`);
    }
    return await resp.json();
  }

  async function getSession(accessToken, sessionId) {
    const doGet = async (token) => fetch(`https://photospicker.googleapis.com/v1/sessions/${encodeURIComponent(sessionId)}`, {
      headers: { 'authorization': `Bearer ${token}` }
    });
    let resp = await doGet(accessToken);
    if (resp.status === 401) {
      const refreshed = await ensureAccessTokenInteractive(true);
      resp = await doGet(refreshed);
    }
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`sessions.get failed: ${resp.status} ${text}`);
    }
    return await resp.json();
  }

  async function pollSessionUntilReady(accessToken, session) {
    const pollIntervalDefault = 3000;
    const timeoutDefault = 5 * 60 * 1000;
    let elapsed = 0;
    let pollInterval = parseDurationToMs(session.pollingConfig?.pollInterval, pollIntervalDefault);
    const timeoutLimit = parseDurationToMs(session.pollingConfig?.timeoutIn, timeoutDefault);

    while (true) {
      const current = await getSession(accessToken, session.id);
      if (current.mediaItemsSet) {
        return current;
      }
      pollInterval = parseDurationToMs(current.pollingConfig?.pollInterval, pollIntervalDefault);
      const timeoutMs = parseDurationToMs(current.pollingConfig?.timeoutIn, timeoutLimit);
      await wait(pollInterval);
      elapsed += pollInterval;
      if (timeoutMs > 0 && elapsed >= timeoutMs) {
        throw new Error('Picker session timed out. Please try again.');
      }
    }
  }

  async function listPickedMediaItems(accessToken, sessionId) {
    const allItems = [];
    let pageToken = undefined;
    while (true) {
      const query = new URLSearchParams({ sessionId });
      if (pageToken) query.set('pageToken', pageToken);
      const doList = async (token) => fetch(`https://photospicker.googleapis.com/v1/mediaItems?${query.toString()}`, {
        headers: { 'authorization': `Bearer ${token}` }
      });
      let resp = await doList(accessToken);
      if (resp.status === 401) {
        const refreshed = await ensureAccessTokenInteractive(true);
        resp = await doList(refreshed);
      }
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`mediaItems.list failed: ${resp.status} ${text}`);
      }
      const json = await resp.json();
      allItems.push(...(json.mediaItems || []));
      if (!json.nextPageToken) {
        return { mediaItems: allItems };
      }
      pageToken = json.nextPageToken;
    }
  }

  async function deleteSession(accessToken, sessionId) {
    if (!sessionId) return;
    const doDelete = async (token) => fetch(`https://photospicker.googleapis.com/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
      headers: { 'authorization': `Bearer ${token}` }
    });
    let resp = await doDelete(accessToken);
    if (resp.status === 401) {
      const refreshed = await ensureAccessTokenInteractive(true);
      resp = await doDelete(refreshed);
    }
    if (!resp.ok && resp.status !== 404) {
      const text = await resp.text();
      appendLog(`WARN: sessions.delete failed: ${resp.status} ${text}`);
    }
  }

  function mapPickedItems(response) {
    const items = response.mediaItems || [];
    return items.map((item) => {
      const media = item.mediaFile || {};
      const baseUrl = media.baseUrl || '';
      return {
        id: item.id,
        source: 'google',
        baseUrl,
        filename: media.filename || `${item.id}.jpg`,
        mimeType: media.mimeType || 'application/octet-stream',
        thumbUrl: buildMediaUrl(baseUrl, 'w400-h400-c'),
        downloadUrl: buildMediaUrl(baseUrl, 'd'),
        status: 'ready',
        progress: 0,
        uploaded: false,
      };
    });
  }

  async function fetchItemBlob(item) {
    if (item.source === 'local') {
      if (item.blob instanceof Blob) {
        return item.blob;
      }
      throw new Error('ローカルファイルのデータを取得できませんでした');
    }
    const attemptFetch = async () => {
      const url = buildMediaUrl(item.baseUrl, 'd');
      item.downloadUrl = url;
      return fetch(url, { mode: 'cors', credentials: 'omit' });
    };
    let resp = await attemptFetch();
    if (resp.status === 401 || resp.status === 400) {
      await ensureAccessTokenInteractive(true);
      refreshAllMediaUrls();
      resp = await attemptFetch();
    }
    if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
    return await resp.blob();
  }

  function renderItems() {
    selectedListEl.innerHTML = '';
    for (const item of state.items) {
      const card = document.createElement('div');
      card.className = 'card';
      const img = document.createElement('img');
      img.className = 'thumb';
      const thumbSrc = item.thumbUrl || buildMediaUrl(item.baseUrl, 'w400-h400-c');
      if (thumbSrc) img.src = thumbSrc;
      img.alt = item.filename || item.id;
      const body = document.createElement('div');
      body.className = 'card-body';
      const name = document.createElement('div');
      name.className = 'filename';
      name.textContent = item.filename;
      const status = document.createElement('div');
      status.className = 'status';
      status.textContent = item.status || '';
      const prog = document.createElement('div');
      prog.className = 'progress';
      const bar = document.createElement('div');
      bar.className = 'bar';
      bar.style.width = `${item.progress || 0}%`;
      prog.appendChild(bar);
      body.appendChild(name);
      body.appendChild(status);
      body.appendChild(prog);
      card.appendChild(img);
      card.appendChild(body);
      selectedListEl.appendChild(card);
      item._els = { status, bar, img };
    }
  }

  function updateItemProgress(item, percent, statusText) {
    item.progress = percent;
    if (item._els?.bar) item._els.bar.style.width = `${percent}%`;
    if (statusText && item._els?.status) item._els.status.textContent = statusText;
  }

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  btnSignIn?.addEventListener('click', async () => {
    await completeSignIn(true);
  });

  overlaySignIn?.addEventListener('click', async () => {
    await completeSignIn(true);
  });

  btnPick?.addEventListener('click', async () => {
    try {
      hidePopupHint();
      if (!state.accessToken) await ensureAccessTokenInteractive();
      let preOpenedWindow = null;
      let popupAttempted = false;
      try {
        preOpenedWindow = window.open('', 'photospicker');
        popupAttempted = true;
      } catch {
        preOpenedWindow = null;
      }
      if (preOpenedWindow && preOpenedWindow.closed) {
        preOpenedWindow = null;
      }
      const session = await createPickerSession(state.accessToken);
      state.lastSessionId = session.id;
      state.lastPickerUri = session.pickerUri;
      appendLog('Picker session created', { sessionId: session.id });
      let navigatedAway = false;
      let popupBlocked = false;
      if (session.pickerUri) {
        let targetWindow = preOpenedWindow && !preOpenedWindow.closed ? preOpenedWindow : null;
        if (!targetWindow) {
          try {
            const manualWindow = window.open(session.pickerUri, '_blank', 'noopener');
            popupAttempted = true;
            if (manualWindow && !manualWindow.closed) {
              targetWindow = manualWindow;
            }
          } catch {
            targetWindow = null;
          }
        }
        if (targetWindow) {
          targetWindow.location.replace(session.pickerUri);
          try { targetWindow.opener = null; } catch {}
          targetWindow.focus?.();
          appendLog('新しいタブで Google Photos Picker を開きました。選択後にこのタブへ戻ってください。');
          hidePopupHint();
        } else {
          popupBlocked = popupAttempted;
          if (popupBlocked) {
            showPopupHint('ブラウザの設定でポップアップとサードパーティログインを許可してから、もう一度「写真を選択」を押してください。');
          }
          savePendingSession(session.id);
          appendLog(popupBlocked
            ? 'INFO: ブラウザがポップアップを許可していないため、同じタブで Picker を開きます。'
            : 'INFO: このまま Picker 画面へ遷移します。選択後にブラウザの戻る操作で本画面へ戻ってください。');
          appendLog('INFO: 選択後にブラウザの戻る操作で本画面へ戻ってください。');
          navigatedAway = true;
          window.location.href = session.pickerUri;
        }
      }
      if (navigatedAway) return;
      const readySession = await pollSessionUntilReady(state.accessToken, session);
      appendLog('Picker session completed');
      const mediaList = await listPickedMediaItems(state.accessToken, readySession.id);
      const localItems = state.items.filter((item) => item.source === 'local');
      const googleItems = mapPickedItems(mediaList);
      state.items = [...localItems, ...googleItems];
      refreshAllMediaUrls();
      renderItems();
      refreshUploadButtonState();
      appendLog(`Picked ${googleItems.length} item(s) from Google Photos (total ${state.items.length})`);
      clearPendingSession();
    } catch (err) {
      appendLog(`ERROR: Picker flow failed: ${err.message}`);
    } finally {
      try {
        const pending = loadPendingSession();
        if (!pending && state.lastSessionId && state.accessToken) {
          await deleteSession(state.accessToken, state.lastSessionId);
          state.lastSessionId = null;
          state.lastPickerUri = null;
        }
      } catch (cleanupErr) {
        appendLog(`WARN: Failed to delete picker session: ${cleanupErr.message}`);
      }
    }
  });

  btnPickLocal?.addEventListener('click', () => {
    if (!inputLocalFiles) return;
    inputLocalFiles.click();
  });

  inputLocalFiles?.addEventListener('change', (event) => {
    const fileList = Array.from(event.target?.files || []);
    if (!fileList.length) return;
    const addedItems = [];
    for (const file of fileList) {
      if (!file) continue;
      if (file.type && !file.type.startsWith('image/')) {
        appendLog(`WARN: 画像ファイルのみ追加できます (${file.name})`);
        continue;
      }
      const item = createLocalItem(file);
      state.items.push(item);
      addedItems.push(item);
    }
    if (addedItems.length) {
      refreshAllMediaUrls();
      renderItems();
      refreshUploadButtonState();
      appendLog(`INFO: ローカルファイルを ${addedItems.length} 件追加しました。`);
    } else {
      appendLog('WARN: 追加できる画像ファイルが選択されませんでした。');
    }
    if (inputLocalFiles) {
      inputLocalFiles.value = '';
    }
  });

  btnUpload?.addEventListener('click', async () => {
    if (!cfg?.upload?.presignEndpoint) {
      appendLog('ERROR: upload.presignEndpoint is not configured in config.js');
      return;
    }
    const pendingItems = state.items.filter((item) => !item.uploaded);
    if (!pendingItems.length) {
      appendLog('INFO: すべての選択済み写真はすでにアップロード済みです。');
      refreshUploadButtonState();
      return;
    }
    try {
      await ensureIdTokenInteractive(false, { allowPrompt: true });
    } catch (err) {
      appendLog(`ERROR: Google にサインインしてください: ${err.message}`);
      return;
    }
    const hasGoogleItems = pendingItems.some((item) => item.source !== 'local');
    if (hasGoogleItems) {
      await ensureAccessTokenInteractive();
    }
    refreshAllMediaUrls();
    for (const item of pendingItems) {
      try {
        updateItemProgress(item, 0, item.source === 'local' ? 'preparing' : 'downloading');
        const blob = await fetchItemBlob(item);
        item.blob = blob;
        const keyPrefix = cfg.upload.s3KeyPrefix || '';
        const safeName = (item.filename || `${item.id}.jpg`).replace(/[^a-zA-Z0-9._-]+/g, '_');
        const datePart = new Date().toISOString().replace(/[:.]/g, '-');
        const key = `${keyPrefix}${datePart}_${safeName}`;
        updateItemProgress(item, 5, 'requesting upload URL');
        const presigned = await getPresigned(key, blob.type || item.mimeType || 'application/octet-stream');
        if (presigned.fields) {
          await xhrUploadPOST(presigned.url, presigned.fields, blob, (p) => updateItemProgress(item, Math.max(5, p), 'uploading (POST)'));
        } else if (presigned.url) {
          await xhrUploadPUT(presigned.url, blob, blob.type || item.mimeType || 'application/octet-stream', (p) => updateItemProgress(item, Math.max(5, p), 'uploading (PUT)'));
        } else {
          throw new Error('Invalid presign response');
        }
        updateItemProgress(item, 100, 'uploaded');
        item.uploaded = true;
        item.status = 'uploaded';
        appendLog(`Uploaded: ${key}`);
      } catch (err) {
        updateItemProgress(item, item.progress || 0, 'error');
        appendLog(`ERROR: Upload failed for ${item.filename || item.id}: ${err.message}`);
      }
    }
    if (cfg?.upload?.manageEndpoint) {
      const currentVisible = state.uploadsVisibleCount || INITIAL_UPLOADS_VISIBLE;
      await fetchUploadsList({ resetVisible: true, offset: 0, limit: Math.max(currentVisible, INITIAL_UPLOADS_VISIBLE) });
    }
    refreshUploadButtonState();
  });

  btnRefreshUploads?.addEventListener('click', () => {
    fetchUploadsList({ resetVisible: true, offset: 0, limit: INITIAL_UPLOADS_VISIBLE });
  });

  btnLoadMoreUploads?.addEventListener('click', () => {
    if (state.uploadsLoading) return;
    const previousVisible = state.uploadsVisibleCount || 0;
    const desiredVisible = previousVisible + UPLOADS_PAGE_STEP;
    const totalCached = state.uploads.length;

    let expandedLocally = 0;
    if (totalCached > previousVisible) {
      const newVisible = Math.min(totalCached, desiredVisible);
      if (newVisible > previousVisible) {
        state.uploadsVisibleCount = newVisible;
        expandedLocally = newVisible - previousVisible;
        renderUploadsList();
        appendLog(`INFO: 既に取得済みの一覧から ${expandedLocally} 件を追加表示しました（合計 ${newVisible} 件）`);
      }
    }

    if (state.uploadsVisibleCount >= desiredVisible) return;

    const totalKnown = typeof state.uploadsTotal === 'number' ? state.uploadsTotal : null;
    if (totalKnown !== null && totalCached >= totalKnown) return;

    const remainingNeed = desiredVisible - (state.uploadsVisibleCount || 0);
    const remainingAvailable = totalKnown !== null ? Math.max(0, totalKnown - totalCached) : null;
    const fetchLimit = remainingAvailable !== null
      ? Math.min(remainingNeed, remainingAvailable)
      : remainingNeed;
    if (fetchLimit <= 0) return;

    const offset = state.nextUploadsOffset ?? state.uploads.length;
    appendLog(`INFO: さらに表示のためサーバーから最大 ${fetchLimit} 件を取得します（offset ${offset}）`);
    fetchUploadsList({ offset, limit: fetchLimit });
  });

  uploadsListEl?.addEventListener('change', (event) => {
    const checkbox = event.target instanceof HTMLInputElement && event.target.classList.contains('upload-select') ? event.target : null;
    if (!checkbox) return;
    toggleUploadSelection(checkbox.dataset.key, checkbox.checked);
  });

  const bulkDeleteBtn = document.getElementById('btnDeleteSelected');
  bulkDeleteBtn?.addEventListener('click', async () => {
    if (!state.uploadsSelected.size) return;
    const keys = Array.from(state.uploadsSelected);
    if (!window.confirm(`選択した ${keys.length} 件を削除しますか？`)) return;
    const originalLabel = bulkDeleteBtn.textContent || '選択した写真を削除';
    bulkDeleteBtn.disabled = true;
    bulkDeleteBtn.textContent = '削除中…';
    try {
      await ensureIdTokenInteractive(false, { allowPrompt: true });
      for (const key of keys) {
        try {
          await deleteUpload(key);
          appendLog(`削除しました: ${key}`);
        } catch (err) {
          appendLog(`ERROR: 削除に失敗しました ${key}: ${err.message}`);
        }
      }
      state.uploadsSelected.clear();
      const currentVisible = state.uploadsVisibleCount || INITIAL_UPLOADS_VISIBLE;
      await fetchUploadsList({ resetVisible: true, offset: 0, limit: Math.max(currentVisible, INITIAL_UPLOADS_VISIBLE) });
    } finally {
      bulkDeleteBtn.textContent = originalLabel;
      bulkDeleteBtn.disabled = false;
      updateBulkDeleteVisibility();
    }
  });

  async function getPresigned(key, contentType) {
    const endpoint = cfg?.upload?.presignEndpoint;
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: Object.assign(
        { 'content-type': 'application/json' },
        state.idToken ? { Authorization: `Bearer ${state.idToken}` } : {}
      ),
      body: JSON.stringify({ key, contentType })
    });
    if (!resp.ok) throw new Error(`Presign endpoint error: ${resp.status}`);
    return await resp.json();
  }

  function xhrUploadPUT(url, blob, contentType, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', url);
      xhr.setRequestHeader('Content-Type', contentType);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onerror = () => reject(new Error('XHR PUT error'));
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(); else reject(new Error(`PUT failed: ${xhr.status}`));
      };
      xhr.send(blob);
    });
  }

  function xhrUploadPOST(url, fields, blob, onProgress) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      Object.entries(fields || {}).forEach(([k, v]) => form.append(k, v));
      form.append('file', blob);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onerror = () => reject(new Error('XHR POST error'));
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(); else reject(new Error(`POST failed: ${xhr.status}`));
      };
      xhr.send(form);
    });
  }

  async function resumePendingSessionIfAny() {
    const pending = loadPendingSession();
    if (!pending) return;
    appendLog('INFO: 前回の Picker セッションを再開しています…');
    try {
      const accessToken = await ensureAccessTokenInteractive();
      const session = await getSession(accessToken, pending.sessionId);
      state.lastSessionId = session.id;
      state.lastPickerUri = session.pickerUri;
      let readySession = session;
      if (!session.mediaItemsSet) {
        readySession = await pollSessionUntilReady(accessToken, session);
      }
      appendLog('Picker session completed');
      const mediaList = await listPickedMediaItems(accessToken, readySession.id);
      const localItems = state.items.filter((item) => item.source === 'local');
      const googleItems = mapPickedItems(mediaList);
      state.items = [...localItems, ...googleItems];
      refreshAllMediaUrls();
      renderItems();
      refreshUploadButtonState();
      appendLog(`Picked ${googleItems.length} item(s) from Google Photos (total ${state.items.length})`);
      clearPendingSession();
      await deleteSession(accessToken, readySession.id).catch((err) => {
        appendLog(`WARN: Failed to delete picker session: ${err.message}`);
      });
      state.lastSessionId = null;
      state.lastPickerUri = null;
    } catch (err) {
      appendLog(`ERROR: 前回セッションの再開に失敗しました: ${err.message}`);
      clearPendingSession();
    }
  }

  const restoredAuth = restoreAuthState();

  // Initialize Sign-In button on load
  initGsi()
    .then(() => {
      if (btnSignIn) btnSignIn.disabled = false;
      if (!state.signedIn) {
        showSigninOverlay();
        if (isLikelyMobile) {
          appendLog('INFO: 最初に「Google にサインイン」をタップして認証してください。');
        } else {
          appendLog('INFO: まず「Google にサインイン」をクリックして認証してください。');
        }
      }
    })
    .catch(() => {});
  window.addEventListener('pageshow', () => {
    if (document.visibilityState === 'visible') {
      resumePendingSessionIfAny().catch(() => {});
    }
  });
  window.addEventListener('beforeunload', () => {
    state.items.forEach((item) => cleanupLocalItem(item));
  });
  resumePendingSessionIfAny().catch(() => {});
})();
