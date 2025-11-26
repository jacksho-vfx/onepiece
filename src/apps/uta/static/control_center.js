const toArray = (collection) => {
    if (!collection) {
      return [];
    }
    if (Array.isArray(collection)) {
      return collection.slice();
    }
    try {
      return Array.from(collection);
    } catch (error) {
      return [].slice.call(collection);
    }
    };

    const tabs = toArray(document.querySelectorAll('.tab-button'));
    const pages = toArray(document.querySelectorAll('.page'));
    const body = document.body || null;
    let defaultDashboardCredentials = null;
    if (body && typeof body.getAttribute === 'function') {
      const encodedDefaults = body.getAttribute('data-dashboard-default-credentials') || '';
      if (encodedDefaults) {
        try {
          const parsedDefaults = JSON.parse(encodedDefaults);
          if (parsedDefaults && typeof parsedDefaults === 'object') {
            defaultDashboardCredentials = parsedDefaults;
          }
        } catch (error) {
          // Ignore malformed defaults; users can still input credentials manually.
        }
      }
    }
    let defaultTabSlug = body && typeof body.getAttribute === 'function'
    ? body.getAttribute('data-default-tab') || ''
    : '';
    const slugToTarget = new Map();
    const targetToSlug = new Map();
    const dashboardTargetId = 'page-dashboard';
    let defaultTargetId = '';

    const setSelectedState = (button, isActive) => {
    if (!button) {
      return;
    }
    if (isActive) {
      button.classList.add('active');
      button.setAttribute('aria-selected', 'true');
    } else {
      button.classList.remove('active');
      button.setAttribute('aria-selected', 'false');
    }
    };

    const togglePageVisibility = (page, shouldBeActive) => {
    if (!page) {
      return;
    }
    if (shouldBeActive) {
      page.classList.add('active');
    } else {
      page.classList.remove('active');
    }
    };

    tabs.forEach((button) => {
    if (!button) {
      return;
    }
    const targetId = button.getAttribute('data-target') || '';
    const slug = button.getAttribute('data-tab') || '';
    const isDefault = button.getAttribute('data-default-tab') === 'true';
    if (slug && targetId) {
      slugToTarget.set(slug, targetId);
      targetToSlug.set(targetId, slug);
    }
    if (isDefault && targetId) {
      defaultTargetId = targetId;
      if (!defaultTabSlug) {
        defaultTabSlug = slug;
      }
    }
    const isActive = button.classList.contains('active');
    setSelectedState(button, isActive);
    });

    if (!defaultTargetId && tabs.length) {
    const fallback = tabs[0];
    if (fallback) {
      defaultTargetId = fallback.getAttribute('data-target') || '';
      const fallbackSlug = fallback.getAttribute('data-tab') || '';
      if (!defaultTabSlug && fallbackSlug) {
        defaultTabSlug = fallbackSlug;
      }
    }
    }

    const resolveTargetFromSlug = (slug) => {
    if (!slug) {
      return '';
    }
    if (slug === 'dashboard') {
      return dashboardTargetId;
    }
    return slugToTarget.get(slug) || '';
    };

    const buildUrlForTarget = (targetId) => {
    const url = new URL(window.location.href);
    if (targetId === dashboardTargetId) {
      url.searchParams.set('tab', 'dashboard');
    } else {
      const slug = targetToSlug.get(targetId) || '';
      if (!slug || slug === defaultTabSlug) {
        url.searchParams.delete('tab');
      } else {
        url.searchParams.set('tab', slug);
      }
    }
    return url;
    };

    const updateBrowserHistory = (targetId, { push } = {}) => {
    if (!window.history || typeof window.history.replaceState !== 'function') {
      return;
    }
    const url = buildUrlForTarget(targetId);
    const current = new URL(window.location.href);
    if (
      current.pathname === url.pathname &&
      current.search === url.search &&
      current.hash === url.hash
    ) {
      return;
    }
    const method = push ? 'pushState' : 'replaceState';
    if (typeof window.history[method] !== 'function') {
      return;
    }
    window.history[method]({ targetId }, '', url);
    };

    function setActive(targetId) {
    if (!targetId) {
      return;
    }
    let targetPage = null;
    for (const page of pages) {
      if (page && page.id === targetId) {
        targetPage = page;
        break;
      }
    }
    if (!targetPage) {
      console.warn('tab.change.missing-page', targetId);
      return;
    }
    tabs.forEach((button) => {
      if (!button) {
        return;
      }
      const buttonTarget = button.getAttribute('data-target') || '';
      setSelectedState(button, buttonTarget === targetId);
    });
    pages.forEach((page) => {
      if (!page) {
        return;
      }
      togglePageVisibility(page, page.id === targetId);
    });
    if (targetId === 'page-dashboard' && typeof window.triggerDashboardRefresh === 'function') {
      window.triggerDashboardRefresh();
    }
    if (targetId === 'page-pipelines' && typeof window.triggerPipelineRefresh === 'function') {
      window.triggerPipelineRefresh();
    }
    }

    const activateTab = (targetId, { pushHistory = false, syncHistory = true } = {}) => {
    if (!targetId) {
      return;
    }
    setActive(targetId);
    if (syncHistory) {
      updateBrowserHistory(targetId, { push: pushHistory });
    }
    };

    const syncToLocation = ({ updateHistory } = {}) => {
    const url = new URL(window.location.href);
    const slug = url.searchParams.get('tab') || '';
    let targetId = resolveTargetFromSlug(slug);
    const hadSlug = Boolean(slug);
    const recognised = Boolean(targetId);
    if (!targetId) {
      targetId = defaultTargetId || dashboardTargetId;
    }
    if (!targetId) {
      targetId = dashboardTargetId;
    }
    const shouldSyncHistory = Boolean(updateHistory) || (hadSlug && !recognised);
    activateTab(targetId, { pushHistory: false, syncHistory: shouldSyncHistory });
    };

    syncToLocation({ updateHistory: true });

    window.addEventListener('popstate', () => {
    syncToLocation({ updateHistory: false });
    });

    tabs.forEach((button) => {
    if (!button) {
      return;
    }
    button.addEventListener('click', (event) => {
      event.preventDefault();
      const targetId = button.getAttribute('data-target');
      if (!targetId) {
        console.warn('tab.change.unknown-target', button);
        return;
      }
      activateTab(targetId, { pushHistory: true, syncHistory: true });
    });
    });

    const commandCards = Array.from(document.querySelectorAll('.command-card'));
    const getVisibleCards = () => commandCards.filter((card) => !card.classList.contains('is-hidden'));
    const isTypingElement = (element) => {
      if (!element) {
        return false;
      }
      const tagName = element.tagName;
      const typingTags = ['INPUT', 'TEXTAREA', 'SELECT', 'OPTION'];
      return typingTags.includes(tagName) || element.isContentEditable === true;
    };
    const findActiveCard = (element) => {
      if (!element || typeof element.closest !== 'function') {
        return null;
      }
      return element.closest('.command-card');
    };
    const focusCard = (card) => {
      if (!card || typeof card.focus !== 'function') {
        return;
      }
      card.focus({ preventScroll: true });
      if (typeof card.scrollIntoView === 'function') {
        card.scrollIntoView({ block: 'nearest' });
      }
    };
    const searchInput = document.getElementById('command-search');
    const favouritesToggle = document.getElementById('favourites-toggle');
    const favouritesPill = document.querySelector('[data-favourites-pill]');
    const filterStatusRegion = document.querySelector('[data-filter-status]');

    const storage = {
      get(key, fallback) {
        try {
          const raw = localStorage.getItem(key);
          return raw === null ? fallback : raw;
        } catch (error) {
          console.warn('localStorage unavailable', error);
          return fallback;
        }
      },
      set(key, value) {
        try {
          localStorage.setItem(key, value);
        } catch (error) {
          console.warn('localStorage unavailable', error);
        }
      },
    };

    const FAVOURITES_KEY = 'uta:favourites';
    const SEARCH_KEY = 'uta:search';
    const FAVOURITES_FILTER_KEY = 'uta:filter:favourites';

    const getInitialFavouritesFilterState = () => {
      const url = new URL(window.location.href);
      const urlFlag = url.searchParams.get('favourites');
      if (urlFlag === 'true') {
        return true;
      }
      if (urlFlag === 'false') {
        return false;
      }
      const storedFlag = storage.get(FAVOURITES_FILTER_KEY, 'false');
      return storedFlag === 'true';
    };

    let favouritesFilterActive = getInitialFavouritesFilterState();
    storage.set(FAVOURITES_FILTER_KEY, String(favouritesFilterActive));

    const favouriteSet = (() => {
      const raw = storage.get(FAVOURITES_KEY, '[]');
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          return new Set(parsed.filter((item) => typeof item === 'string'));
        }
      } catch (error) {
        console.warn('Unable to parse favourites', error);
      }
      return new Set();
    })();

    const persistFavourites = () => {
      storage.set(FAVOURITES_KEY, JSON.stringify(Array.from(favouriteSet)));
    };

    const updateFavouriteUI = (card, isFavourite) => {
      const button = card.querySelector('.favourite-toggle');
      const icon = button ? button.querySelector('.favourite-icon') : null;
      card.classList.toggle('is-favourite', isFavourite);
      if (button) {
        button.setAttribute('aria-pressed', String(isFavourite));
        button.classList.toggle('is-active', isFavourite);
      }
      if (icon) {
        icon.textContent = isFavourite ? '★' : '☆';
      }
    };

    const buildFavouritesFilterUrl = (isActive) => {
      const url = new URL(window.location.href);
      if (isActive) {
        url.searchParams.set('favourites', 'true');
      } else {
        url.searchParams.delete('favourites');
      }
      return url;
    };

    const syncFavouritesFilterHistory = (isActive) => {
      if (!window.history || typeof window.history.replaceState !== 'function') {
        return;
      }
      const url = buildFavouritesFilterUrl(isActive);
      const current = new URL(window.location.href);
      if (
        current.pathname === url.pathname &&
        current.search === url.search &&
        current.hash === url.hash
      ) {
        return;
      }
      window.history.replaceState({ favouritesOnly: isActive }, '', url);
    };

    const updateFavouritesFilterUI = (isActive) => {
      if (favouritesToggle) {
        favouritesToggle.checked = isActive;
      }
      if (favouritesPill) {
        favouritesPill.classList.toggle('is-active', isActive);
        favouritesPill.setAttribute('aria-pressed', String(isActive));
        favouritesPill.setAttribute(
          'aria-label',
          isActive ? 'Favourites filter on. Showing favourites only.' : 'Show favourite commands only',
        );
      }
    };

    const announceFilterState = (isActive) => {
      if (!filterStatusRegion) {
        return;
      }
      filterStatusRegion.textContent = isActive
        ? 'Favourites filter enabled. Showing favourite commands only.'
        : 'Favourites filter disabled. Showing all commands.';
    };

    function applyFilter() {
      const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
      const favouritesOnly = favouritesFilterActive;
      commandCards.forEach((card) => {
        const keywords = card.dataset.keywords || '';
        const matchesQuery = !query || keywords.includes(query);
        const matchesFavourite = !favouritesOnly || card.classList.contains('is-favourite');
        const visible = matchesQuery && matchesFavourite;
        card.classList.toggle('is-hidden', !visible);
        card.setAttribute('aria-hidden', String(!visible));
      });
    }

    const setFavouritesFilter = (isActive, { announce = false } = {}) => {
      const nextState = Boolean(isActive);
      favouritesFilterActive = nextState;
      storage.set(FAVOURITES_FILTER_KEY, String(nextState));
      updateFavouritesFilterUI(nextState);
      syncFavouritesFilterHistory(nextState);
      if (announce) {
        announceFilterState(nextState);
      }
      applyFilter();
    };

    updateFavouritesFilterUI(favouritesFilterActive);
    announceFilterState(favouritesFilterActive);
    syncFavouritesFilterHistory(favouritesFilterActive);

    commandCards.forEach((card) => {
      const id = card.dataset.commandId;
      if (!id) {
        return;
      }
      const isFavourite = favouriteSet.has(id);
      updateFavouriteUI(card, isFavourite);
      const button = card.querySelector('.favourite-toggle');
      if (button) {
        button.addEventListener('click', () => {
          if (favouriteSet.has(id)) {
            favouriteSet.delete(id);
          } else {
            favouriteSet.add(id);
          }
          persistFavourites();
          updateFavouriteUI(card, favouriteSet.has(id));
          applyFilter();
        });
      }
    });

    if (searchInput) {
      const storedSearch = storage.get(SEARCH_KEY, '');
      searchInput.value = storedSearch;
      searchInput.addEventListener('input', () => {
        storage.set(SEARCH_KEY, searchInput.value);
        applyFilter();
      });
    }

    if (favouritesToggle) {
      favouritesToggle.addEventListener('change', () => {
        setFavouritesFilter(favouritesToggle.checked, { announce: true });
      });
    }

    if (favouritesPill) {
      favouritesPill.addEventListener('click', () => {
        setFavouritesFilter(!favouritesFilterActive, { announce: true });
      });
    }

    applyFilter();

    document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !(event.ctrlKey || event.metaKey || event.altKey)) {
      const activeElement = document.activeElement;
      if (!isTypingElement(activeElement) && searchInput) {
        event.preventDefault();
        searchInput.focus();
        searchInput.select();
      }
    }
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !(event.ctrlKey || event.metaKey || event.altKey)) {
      const activeElement = document.activeElement;
      if (isTypingElement(activeElement)) {
        return;
      }
      const visibleCards = getVisibleCards();
      if (!visibleCards.length) {
        return;
      }
      const currentCard = findActiveCard(activeElement);
      const currentIndex = visibleCards.indexOf(currentCard);
      const isArrowDown = event.key === 'ArrowDown';
      let targetIndex = isArrowDown ? 0 : visibleCards.length - 1;
      if (currentIndex >= 0) {
        targetIndex = isArrowDown
          ? Math.min(currentIndex + 1, visibleCards.length - 1)
          : Math.max(currentIndex - 1, 0);
      }
      const targetCard = visibleCards[targetIndex];
      if (targetCard) {
        event.preventDefault();
        focusCard(targetCard);
      }
    }
    if (event.key === 'Enter' && !(event.ctrlKey || event.metaKey || event.altKey)) {
      const activeElement = document.activeElement;
      if (isTypingElement(activeElement)) {
        return;
      }
      const card = findActiveCard(activeElement);
      const runButton = card ? card.querySelector('.run-command') : null;
      if (runButton) {
        event.preventDefault();
        runButton.click();
      }
    }
    if (event.key.toLowerCase() === 'f' && event.shiftKey && !(event.ctrlKey || event.metaKey || event.altKey)) {
      const activeElement = document.activeElement;
      const card = findActiveCard(activeElement);
      if (card) {
        event.preventDefault();
        const button = card.querySelector('.favourite-toggle');
        if (button) {
        button.click();
        }
      }
    }
    if (event.key.toLowerCase() === 'c' && event.shiftKey && !(event.ctrlKey || event.metaKey || event.altKey)) {
      const activeElement = document.activeElement;
      const card = findActiveCard(activeElement);
      if (card) {
        const button = card.querySelector('.copy-command');
        if (button) {
        event.preventDefault();
        button.click();
        }
      }
    }
    });

    const rootPath = document.body.dataset.rootPath || "";
    const joinWithRoot = (path) => (rootPath ? `${rootPath}${path}` : path);
    const DASHBOARD_API_KEY_KEY = 'uta:dashboard:apiKey';
    const DASHBOARD_API_SECRET_KEY = 'uta:dashboard:apiSecret';
    const DASHBOARD_BEARER_KEY = 'uta:dashboard:bearerToken';
    const requireCredentialsMessage = 'Add Trafalgar credentials above to load analytics.';
    const authFailureMessage = 'Authentication failed. Verify the credentials above.';
    const dashboardAuthCard = document.querySelector('[data-dashboard-auth]');
    const apiKeyInput = dashboardAuthCard ? dashboardAuthCard.querySelector('[data-dashboard-api-key]') : null;
    const apiSecretInput = dashboardAuthCard ? dashboardAuthCard.querySelector('[data-dashboard-api-secret]') : null;
    const bearerInput = dashboardAuthCard ? dashboardAuthCard.querySelector('[data-dashboard-bearer]') : null;
    const clearCredentialsButton = dashboardAuthCard ? dashboardAuthCard.querySelector('[data-dashboard-auth-clear]') : null;
    const sanitizeCredential = (value) => (typeof value === 'string' ? value.trim() : '');
    let dashboardCredentials = {
    apiKey: sanitizeCredential(storage.get(DASHBOARD_API_KEY_KEY, '')),
    apiSecret: sanitizeCredential(storage.get(DASHBOARD_API_SECRET_KEY, '')),
    bearerToken: sanitizeCredential(storage.get(DASHBOARD_BEARER_KEY, '')),
    };
    const persistDashboardCredentials = () => {
    storage.set(DASHBOARD_API_KEY_KEY, dashboardCredentials.apiKey);
    storage.set(DASHBOARD_API_SECRET_KEY, dashboardCredentials.apiSecret);
    storage.set(DASHBOARD_BEARER_KEY, dashboardCredentials.bearerToken);
    };
    const applyDefaultDashboardCredentials = () => {
    if (!defaultDashboardCredentials || typeof defaultDashboardCredentials !== 'object') {
      return;
    }
    const maybeApply = (field, value) => {
      if (typeof value !== 'string') {
      return false;
      }
      const sanitised = sanitizeCredential(value);
      if (!sanitised || dashboardCredentials[field]) {
      return false;
      }
      dashboardCredentials[field] = sanitised;
      return true;
    };
    let changed = maybeApply('bearerToken', defaultDashboardCredentials.bearerToken);
    changed = maybeApply('apiKey', defaultDashboardCredentials.apiKey) || changed;
    changed = maybeApply('apiSecret', defaultDashboardCredentials.apiSecret) || changed;
    if (changed) {
      persistDashboardCredentials();
    }
    };
    const updateAuthCardState = (stateOverride) => {
    if (!dashboardAuthCard) {
      return;
    }
    if (stateOverride) {
      dashboardAuthCard.dataset.authState = stateOverride;
      return;
    }
    if (dashboardCredentials.bearerToken || dashboardCredentials.apiKey) {
      dashboardAuthCard.dataset.authState = 'ready';
    } else {
      delete dashboardAuthCard.dataset.authState;
    }
    };
    const requestDashboardRefresh = () => {
    if (typeof window.triggerDashboardRefresh === 'function') {
      window.triggerDashboardRefresh();
    }
    if (typeof window.triggerPipelineRefresh === 'function') {
      window.triggerPipelineRefresh();
    }
    };
    const resolveDashboardHeaders = () => {
    if (dashboardCredentials.bearerToken) {
      return {
        Authorization: `Bearer ${dashboardCredentials.bearerToken}`,
      };
    }
    if (dashboardCredentials.apiKey) {
      const headers = {
        'X-API-Key': dashboardCredentials.apiKey,
      };
      if (dashboardCredentials.apiSecret) {
        headers['X-API-Secret'] = dashboardCredentials.apiSecret;
      }
      return headers;
    }
    return null;
    };
    applyDefaultDashboardCredentials();
    updateAuthCardState();
    if (apiKeyInput) {
    apiKeyInput.value = dashboardCredentials.apiKey;
    apiKeyInput.addEventListener('input', () => {
      dashboardCredentials.apiKey = sanitizeCredential(apiKeyInput.value);
      persistDashboardCredentials();
      updateAuthCardState();
    });
    apiKeyInput.addEventListener('change', requestDashboardRefresh);
    }
    if (apiSecretInput) {
    apiSecretInput.value = dashboardCredentials.apiSecret;
    apiSecretInput.addEventListener('input', () => {
      dashboardCredentials.apiSecret = sanitizeCredential(apiSecretInput.value);
      persistDashboardCredentials();
    });
    apiSecretInput.addEventListener('change', requestDashboardRefresh);
    }
    if (bearerInput) {
    bearerInput.value = dashboardCredentials.bearerToken;
    bearerInput.addEventListener('input', () => {
      dashboardCredentials.bearerToken = sanitizeCredential(bearerInput.value);
      persistDashboardCredentials();
      updateAuthCardState();
    });
    bearerInput.addEventListener('change', requestDashboardRefresh);
    }
    if (clearCredentialsButton) {
    clearCredentialsButton.addEventListener('click', () => {
      dashboardCredentials = {
        apiKey: '',
        apiSecret: '',
        bearerToken: '',
      };
      if (apiKeyInput) {
        apiKeyInput.value = '';
      }
      if (apiSecretInput) {
        apiSecretInput.value = '';
      }
      if (bearerInput) {
        bearerInput.value = '';
      }
      persistDashboardCredentials();
      updateAuthCardState();
      requestDashboardRefresh();
    });
    }
    const safeParseJson = (value, fallback) => {
    try {
      return JSON.parse(value);
    } catch (error) {
      return fallback;
    }
    };
    const backslashChar = String.fromCharCode(92);
    const carriageReturn = String.fromCharCode(13);
    const lineFeed = String.fromCharCode(10);
    const quoteArgument = (segment) => {
    if (typeof segment !== 'string' || segment.length === 0) {
      return "''";
    }
    const hasWhitespaceOrQuotes = /[\s"']/.test(segment);
    if (!hasWhitespaceOrQuotes && !segment.includes(backslashChar)) {
      return segment;
    }
    return `'${segment.replace(/'/g, "'\''")}'`;
    };
    const expandMultiValue = (input, raw) => {
    if (typeof raw !== 'string') {
      return [];
    }
    const trimmed = raw.trim();
    if (!trimmed) {
      return [];
    }
    if (input.dataset.allowMultiple === 'true') {
      return trimmed
        .replaceAll(carriageReturn, lineFeed)
        .split(lineFeed)
        .map((value) => value.trim())
        .filter((value) => value.length > 0);
    }
    return [trimmed];
    };
    const pickPreferredOptionName = (names) => {
    if (!Array.isArray(names)) {
      return '';
    }
    for (const name of names) {
      if (typeof name === 'string' && !name.startsWith('--no-')) {
        return name;
      }
    }
    return names.find((name) => typeof name === 'string') || '';
    };
    const pickNegativeOptionName = (names) => {
    if (!Array.isArray(names)) {
      return '';
    }
    return (
      names.find((name) => typeof name === 'string' && name.startsWith('--no-')) ||
      ''
    );
    };
    document.querySelectorAll('.command-form').forEach((form) => {
    const card = form.closest('.command-card');
    const output = card.querySelector('.command-output');
    const status = form.querySelector('.status');
    const progress = form.querySelector('.progress-indicator');
    const preview = card.querySelector('.command-invocation');
    const baseSegments = preview && preview.dataset.commandBase
      ? safeParseJson(preview.dataset.commandBase, [])
      : [];
    const commandPathRaw = (card.dataset.commandPath || '').trim();
    const commandPath = commandPathRaw ? commandPathRaw.split(/\s+/) : [];
    const parameterInputs = Array.from(
      form.querySelectorAll('.command-parameter'),
    );
    const copyButton = form.querySelector('.copy-command');
    const executedCopyButton = form.querySelector('.copy-executed-command');
    const downloadOutputButton = form.querySelector('.download-output');
    let lastInvocationText = '';
    let copyFeedbackTimer = null;
    let statusResetTimer = null;
    const resolveBaseSegments = () => (
      Array.isArray(baseSegments) && baseSegments.length
        ? baseSegments
        : ['onepiece', ...commandPath]
    );
    const escapeId = (value) => {
      if (typeof CSS !== 'undefined' && CSS.escape) {
        return CSS.escape(value);
      }
      return value.replace(/[^\w-]/g, '\\$&');
    };
    const findInputById = (targetId) => {
      if (!targetId) {
        return null;
      }
      return form.querySelector(`#${escapeId(targetId)}`);
    };
    const mergePresetValues = (targetId, values) => {
      if (!Array.isArray(values) || values.length === 0) {
        return;
      }
      const input = findInputById(targetId);
      if (!input || input.dataset.allowMultiple !== 'true') {
        return;
      }
      const existing = expandMultiValue(input, input.value || '');
      const nextValues = existing.slice();
      values.forEach((value) => {
        const text = typeof value === 'string' ? value.trim() : String(value || '').trim();
        if (text && !nextValues.includes(text)) {
          nextValues.push(text);
        }
      });
      input.value = nextValues.join(lineFeed);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const clearStatusTimer = () => {
      if (statusResetTimer) {
        clearTimeout(statusResetTimer);
        statusResetTimer = null;
      }
    };
    const setTemporaryStatus = (message, state) => {
      if (!status) {
        return;
      }
      if (status.dataset.state === 'running') {
        if (state === 'error' && message) {
        status.title = message;
        }
        return;
      }
      const previous = {
        text: status.textContent || '',
        state: status.dataset.state || '',
        title: status.getAttribute('title') || '',
      };
      clearStatusTimer();
      const targetState = state || '';
      status.textContent = message || '';
      if (targetState) {
        status.dataset.state = targetState;
      } else {
        status.removeAttribute('data-state');
      }
      if (targetState === 'error' && message) {
        status.title = message;
      } else {
        status.removeAttribute('title');
      }
      statusResetTimer = setTimeout(() => {
        const currentText = status.textContent || '';
        const currentState = status.dataset.state || '';
        if (currentText === (message || '') && currentState === targetState) {
        if (previous.state) {
          status.dataset.state = previous.state;
        } else {
          status.removeAttribute('data-state');
        }
        status.textContent = previous.text;
        if (previous.title) {
          status.title = previous.title;
        } else {
          status.removeAttribute('title');
        }
        }
        statusResetTimer = null;
      }, 2200);
    };
    const setCopyFeedback = (state, overrideLabel) => {
      if (!copyButton) {
        return;
      }
      const label = copyButton.querySelector('.button-label');
      if (!label) {
        return;
      }
      const defaultLabel = copyButton.dataset.defaultLabel || label.textContent || 'Copy command';
      if (!copyButton.dataset.defaultLabel) {
        copyButton.dataset.defaultLabel = defaultLabel;
      }
      if (copyFeedbackTimer) {
        clearTimeout(copyFeedbackTimer);
        copyFeedbackTimer = null;
      }
      copyButton.classList.remove('is-copied', 'is-error');
      if (state === 'success') {
        copyButton.classList.add('is-copied');
        label.textContent = overrideLabel || 'Copied!';
      } else if (state === 'error') {
        copyButton.classList.add('is-error');
        label.textContent = overrideLabel || 'Copy failed';
      } else {
        label.textContent = defaultLabel;
        return;
      }
      copyFeedbackTimer = setTimeout(() => {
        copyButton.classList.remove('is-copied', 'is-error');
        label.textContent = copyButton.dataset.defaultLabel || 'Copy command';
        copyFeedbackTimer = null;
      }, 2000);
    };
    const copyTextToClipboard = async (value) => {
      if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(value);
        return;
      }
      const bodyElement = typeof document !== 'undefined' ? document.body : null;
      if (!bodyElement) {
        throw new Error('Clipboard copy is not supported');
      }
      const helper = document.createElement('textarea');
      helper.value = value;
      helper.setAttribute('readonly', '');
      helper.style.position = 'fixed';
      helper.style.opacity = '0';
      helper.style.pointerEvents = 'none';
      bodyElement.appendChild(helper);
      helper.focus();
      helper.select();
      let successful = false;
      try {
        successful = typeof document.execCommand === 'function' ? document.execCommand('copy') : false;
      } catch (error) {
        successful = false;
      }
      bodyElement.removeChild(helper);
      if (!successful) {
        throw new Error('Clipboard copy is not supported');
      }
    };
    const buildArgumentSegments = () => {
      const segments = [];
      parameterInputs.forEach((input) => {
        const isFlag = input.dataset.isFlag === 'true';
        const kind = input.dataset.parameterKind;
        const names = safeParseJson(input.dataset.cliNames || '[]', []);
        if (isFlag) {
        const defaultStateAttr = input.dataset.defaultState;
        const defaultState =
          defaultStateAttr === 'true'
          ? true
          : defaultStateAttr === 'false'
          ? false
          : null;
        const negativeName = pickNegativeOptionName(names);
        if (defaultState === null) {
          if (input.checked) {
          const name = pickPreferredOptionName(names);
          if (name) {
            segments.push(name);
          }
          }
          return;
        }
        if (input.checked === defaultState) {
          return;
        }
        if (input.checked) {
          const name = pickPreferredOptionName(names);
          if (name) {
          segments.push(name);
          }
          return;
        }
        if (!input.checked && negativeName) {
          segments.push(negativeName);
        }
        return;
        }
        if (kind === 'option') {
        const values = expandMultiValue(input, input.value);
        if (!values.length) {
          return;
        }
        const optionName = pickPreferredOptionName(names);
        if (!optionName) {
          values.forEach((value) => segments.push(value));
          return;
        }
        values.forEach((value) => {
          segments.push(optionName);
          segments.push(value);
        });
        return;
        }
        const values = expandMultiValue(input, input.value);
        values.forEach((value) => segments.push(value));
      });
      return segments;
    };
    const buildInvocationSegments = () => {
      const base = resolveBaseSegments();
      return [...base, ...buildArgumentSegments()];
    };
    const updatePostRunButtons = (isBusy = false) => {
      if (executedCopyButton) {
        if (isBusy) {
          executedCopyButton.disabled = true;
          executedCopyButton.dataset.state = 'busy';
        } else {
          const ready = Boolean(lastInvocationText.trim());
          executedCopyButton.disabled = !ready;
          executedCopyButton.dataset.state = ready ? 'ready' : 'disabled';
        }
      }
      if (downloadOutputButton) {
        const outputReady =
          !isBusy &&
          output &&
          !output.hidden &&
          Boolean((output.textContent || '').trim());
        downloadOutputButton.disabled = !outputReady;
        downloadOutputButton.dataset.state = isBusy
          ? 'busy'
          : outputReady
          ? 'ready'
          : 'disabled';
      }
    };
    const updatePreview = () => {
      if (!preview) {
        return;
      }
      const previewSegments = buildInvocationSegments();
      preview.textContent = previewSegments.map(quoteArgument).join(' ');
    };
    const presetSelectors = form.querySelectorAll('.parameter-preset');
    presetSelectors.forEach((select) => {
      select.addEventListener('change', () => {
        const targetId = select.dataset.target || '';
        const selected = select.options[select.selectedIndex];
        const rawValues = selected
          ? safeParseJson(selected.dataset.values || '[]', [])
          : [];
        mergePresetValues(targetId, rawValues);
        select.value = '';
      });
    });
    const exampleButtons = form.querySelectorAll('.parameter-helper-chip');
    exampleButtons.forEach((button) => {
      button.addEventListener('click', () => {
        mergePresetValues(button.dataset.target || '', [button.dataset.example || '']);
      });
    });
    parameterInputs.forEach((input) => {
      const eventName = input.type === 'checkbox' ? 'change' : 'input';
      input.addEventListener(eventName, updatePreview);
    });
    updatePreview();
    updatePostRunButtons(false);
    if (copyButton) {
      copyButton.addEventListener('click', async () => {
        if (!preview) {
        return;
        }
        const commandText = preview.textContent || '';
        if (!commandText.trim()) {
        setCopyFeedback('error', 'Nothing to copy');
        setTemporaryStatus('Nothing to copy', 'error');
        return;
        }
        try {
        await copyTextToClipboard(commandText);
        setCopyFeedback('success', 'Copied!');
        setTemporaryStatus('Command copied', 'info');
        } catch (error) {
        const message = error && typeof error.message === 'string'
          ? error.message
          : 'Unable to copy command';
        setCopyFeedback('error', 'Copy failed');
        setTemporaryStatus(message, 'error');
        }
      });
    }
    if (executedCopyButton) {
      executedCopyButton.addEventListener('click', async () => {
        if (!lastInvocationText.trim()) {
          setTemporaryStatus('Run a command to capture the invocation', 'error');
          return;
        }
        try {
          await copyTextToClipboard(lastInvocationText);
          setTemporaryStatus('Executed command copied', 'info');
          executedCopyButton.dataset.state = 'ready';
        } catch (error) {
          const message = error && typeof error.message === 'string'
            ? error.message
            : 'Unable to copy executed command';
          setTemporaryStatus(message, 'error');
          executedCopyButton.dataset.state = 'disabled';
        }
      });
    }
    if (downloadOutputButton) {
      downloadOutputButton.addEventListener('click', () => {
        const outputText = output && typeof output.textContent === 'string'
          ? output.textContent
          : '';
        if (!outputText.trim()) {
          setTemporaryStatus('No output available to download', 'error');
          downloadOutputButton.dataset.state = 'disabled';
          return;
        }
        const blob = new Blob([outputText], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const filename = `${commandPath.join('_') || 'command'}_output.txt`;
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        requestAnimationFrame(() => {
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
        });
        setTemporaryStatus('Download started', 'info');
        downloadOutputButton.dataset.state = 'ready';
      });
    }
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('.run-command');
      if (!button) {
        return;
      }
      const path = commandPath.slice();
      if (!path.length) {
        clearStatusTimer();
        status.textContent = 'Unknown command';
        status.dataset.state = 'error';
        return;
      }
      const argumentSegments = buildArgumentSegments();
      const invocationSegments = buildInvocationSegments();
      lastInvocationText = invocationSegments.map(quoteArgument).join(' ');
      const extraArgsString = argumentSegments.map(quoteArgument).join(' ');
      clearStatusTimer();
      button.disabled = true;
      card.classList.add('is-busy');
      status.removeAttribute('data-state');
      status.textContent = 'Running…';
      status.dataset.state = 'running';
      status.removeAttribute('title');
      updatePostRunButtons(true);
      if (progress) {
        progress.hidden = false;
      }
      output.hidden = true;
      output.textContent = '';
      try {
        const response = await fetch(joinWithRoot('/api/run'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, arguments: argumentSegments, extra_args: extraArgsString }),
        });
        const data = await response.json();
        if (!response.ok) {
        throw new Error(data.detail || 'Command failed');
        }
    const stripTrailingLineBreak = (text) => {
      if (typeof text !== 'string' || text.length === 0) {
        return '';
      }
      let result = text;
      if (result.endsWith(lineFeed)) {
        result = result.slice(0, -1);
        if (result.endsWith(carriageReturn)) {
        result = result.slice(0, -1);
        }
      } else if (result.endsWith(carriageReturn)) {
        result = result.slice(0, -1);
      }
      return result;
    };
        const sanitizeSegment = (value) => {
        if (typeof value !== 'string') {
          return null;
        }
        const cleaned = stripTrailingLineBreak(value);
        return cleaned.length > 0 ? cleaned : null;
        };

        const segments = [];
        const stdoutSegment = sanitizeSegment(data.stdout);
        if (stdoutSegment !== null) {
        segments.push(stdoutSegment);
        }

        const stderrSegment = sanitizeSegment(data.stderr);
        if (stderrSegment !== null) {
        segments.push('\n[stderr]\n' + stderrSegment);
        }

        segments.push(`
(exit code: ${data.exit_code})`);
        output.textContent = segments.join('\n');
        output.hidden = false;
        clearStatusTimer();
        if (data.success) {
        status.textContent = 'Completed';
        status.dataset.state = 'success';
        status.removeAttribute('title');
        } else {
        status.textContent = `Failed (exit code ${data.exit_code})`;
        status.dataset.state = 'error';
        status.removeAttribute('title');
        }
        setTemporaryStatus('Run finished. Actions ready.', 'info');
      } catch (error) {
        const message = error && typeof error.message === 'string' ? error.message : 'Unexpected error';
        output.textContent = message;
        output.hidden = false;
        clearStatusTimer();
        status.textContent = 'Request error';
        status.dataset.state = 'error';
        status.title = message;
        setTemporaryStatus('Run finished with errors. Actions ready.', 'error');
      } finally {
        button.disabled = false;
        card.classList.remove('is-busy');
        updatePostRunButtons(false);
        if (progress) {
        progress.hidden = true;
        }
      }
    });
    });

    (function setupPipelineOrchestrator() {
    const pipelinePage = document.querySelector('[data-pipeline-page]');
    if (!pipelinePage) {
      return;
    }
    const cardsContainer = pipelinePage.querySelector('[data-pipeline-cards]');
    const searchInput = pipelinePage.querySelector('[data-pipeline-search]');
    const statusChips = pipelinePage.querySelector('[data-pipeline-status-chips]');
    const emptyState = pipelinePage.querySelector('[data-pipeline-empty]');
    const errorBox = pipelinePage.querySelector('[data-pipeline-error]');
    const refreshButton = pipelinePage.querySelector('[data-pipeline-refresh]');
    const statusElement = pipelinePage.querySelector('[data-pipeline-status]');
    const template = document.getElementById('pipeline-card-template');
    if (!cardsContainer || !template) {
      return;
    }

    const NO_CREDENTIALS_CODE = 'no-credentials';
    let loaded = false;
    let loading = false;
    let pipelinesCache = [];
    let activeStatusFilter = 'all';

    const normaliseStatus = (value) => {
      if (typeof value !== 'string') {
        return '';
      }
      return value.trim().toLowerCase();
    };

    const normaliseSeverity = (value) => {
      const resolved = normaliseStatus(value);
      if (!resolved) {
        return 'info';
      }
      if (resolved.includes('error') || resolved.includes('fail')) {
        return 'error';
      }
      if (resolved.includes('warn')) {
        return 'warning';
      }
      if (resolved.includes('success') || resolved === 'ok' || resolved === 'succeeded') {
        return 'success';
      }
      return resolved;
    };

    const setStatus = (message, state) => {
      if (!statusElement) {
        return;
      }
      statusElement.textContent = message || '';
      if (state) {
        statusElement.dataset.state = state;
      } else {
        delete statusElement.dataset.state;
      }
    };

    const showError = (message) => {
      if (!errorBox) {
        return;
      }
      if (message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
      } else {
        errorBox.textContent = '';
        errorBox.hidden = true;
      }
    };

    const updateEmptyState = (hasContent) => {
      if (!emptyState) {
        return;
      }
      emptyState.hidden = hasContent;
    };

    const applyPipelineFilters = () => {
      const query = searchInput && searchInput.value ? searchInput.value.trim().toLowerCase() : '';
      let visibleCount = 0;
      const cards = Array.from(cardsContainer.querySelectorAll('[data-pipeline-card]'));
      cards.forEach((card) => {
        const displayName = (card.dataset.displayName || card.dataset.name || '').toLowerCase();
        const identifier = (card.dataset.identifier || '').toLowerCase();
        const status = normaliseStatus(card.dataset.status) || 'unknown';
        const matchesQuery = !query || displayName.includes(query) || identifier.includes(query);
        const matchesStatus = activeStatusFilter === 'all' || status === activeStatusFilter;
        const visible = matchesQuery && matchesStatus;
        card.hidden = !visible;
        if (visible) {
          visibleCount += 1;
        }
      });
      updateEmptyState(visibleCount > 0);
      return visibleCount;
    };

    const renderStatusFilters = (pipelines) => {
      if (!statusChips) {
        return;
      }
      const statuses = new Set(
        (pipelines || [])
          .map((pipeline) => normaliseStatus(pipeline && (pipeline.status || pipeline.state || pipeline.pipeline_status)))
          .filter((status) => Boolean(status)),
      );
      const options = ['all', ...Array.from(statuses).sort()];
      if (!options.includes(activeStatusFilter)) {
        activeStatusFilter = 'all';
      }
      statusChips.innerHTML = '';
      options.forEach((status) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `pipeline-status-chip${status === activeStatusFilter ? ' is-active' : ''}`;
        button.dataset.pipelineStatusChip = '';
        button.dataset.status = status;
        button.textContent = status === 'all' ? 'All statuses' : status;
        button.addEventListener('click', () => {
          activeStatusFilter = status;
          Array.from(statusChips.querySelectorAll('[data-pipeline-status-chip]')).forEach((chip) => {
            chip.classList.toggle('is-active', chip === button);
          });
          applyPipelineFilters();
        });
        statusChips.appendChild(button);
      });
    };

    const buildHeaders = (needsJson = false) => {
      if (typeof resolveDashboardHeaders !== 'function') {
        return null;
      }
      const base = resolveDashboardHeaders();
      if (!base) {
        return null;
      }
      const headers = Object.assign({}, base);
      if (needsJson) {
        headers['Content-Type'] = 'application/json';
      }
      return headers;
    };

    const requestJson = async (path, { method = 'GET', body } = {}) => {
      const headers = buildHeaders(method !== 'GET' && method !== 'HEAD');
      if (!headers) {
        const error = new Error('Pipeline credentials are required.');
        error.code = NO_CREDENTIALS_CODE;
        throw error;
      }
      const options = { method, headers, credentials: 'same-origin' };
      if (body !== undefined) {
        options.body = body;
      }
      const response = await fetch(joinWithRoot(path), options);
      if ([401, 403].includes(response.status)) {
        throw new Error('Authentication failed. Update Trafalgar credentials and retry.');
      }
      if (!response.ok) {
        let detail = `Pipeline request failed (${response.status})`;
        try {
        const payload = await response.json();
        if (payload && typeof payload.detail === 'string') {
          detail = payload.detail;
        }
        } catch (error) {
        // ignore JSON parsing issues
        }
        throw new Error(detail);
      }
      if (response.status === 204) {
        return null;
      }
      return response.json();
    };

    const formatTimestamp = (value) => {
      if (!value) {
        return '';
      }
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return value;
      }
      return date.toLocaleString();
    };

    const getTimestampValue = (value) => {
      if (!value) {
        return null;
      }
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return null;
      }
      return date.getTime();
    };

    const renderEvents = (card, events) => {
      const section = card.querySelector('[data-pipeline-events]');
      const list = card.querySelector('[data-pipeline-event-list]');
      if (!section || !list) {
        return;
      }
      list.innerHTML = '';
      const entries = Array.isArray(events) ? events.filter(Boolean) : [];
      if (!entries.length) {
        section.hidden = true;
        return;
      }
      const runLookup = new Map();
      entries.forEach((event) => {
        const runId =
          (event && (event.run_id || event.runId || event.pipeline_run_id)) || card.dataset.lastRunId || 'latest';
        if (!runLookup.has(runId)) {
          runLookup.set(runId, []);
        }
        runLookup.get(runId).push(event);
      });

      const runEntries = Array.from(runLookup.entries()).map(([runId, runEvents]) => {
        const sorted = runEvents.slice().sort((left, right) => {
          const leftTime = getTimestampValue(left && left.timestamp) || 0;
          const rightTime = getTimestampValue(right && right.timestamp) || 0;
          return leftTime - rightTime;
        });
        const latest = sorted[sorted.length - 1] || null;
        return { runId, events: sorted, latestTimestamp: latest ? getTimestampValue(latest.timestamp) : null };
      });

      runEntries.sort((left, right) => {
        const leftTime = left.latestTimestamp || 0;
        const rightTime = right.latestTimestamp || 0;
        return rightTime - leftTime;
      });

      runEntries.forEach(({ runId, events: runEvents, latestTimestamp }) => {
        const item = document.createElement('li');
        item.className = 'pipeline-event-run';

        const header = document.createElement('div');
        header.className = 'pipeline-event-run-header';
        const title = document.createElement('span');
        title.className = 'pipeline-event-run-title';
        title.textContent = runId ? `Run ${runId}` : 'Latest run';
        header.appendChild(title);
        if (latestTimestamp !== null) {
          const time = document.createElement('span');
          time.className = 'pipeline-event-run-time';
          time.textContent = formatTimestamp(latestTimestamp);
          header.appendChild(time);
        }
        item.appendChild(header);

        const runList = document.createElement('ul');
        runList.className = 'pipeline-event-run-list';

        runEvents.forEach((event) => {
          const entry = document.createElement('li');
          entry.className = 'pipeline-event-entry';
          const severity = normaliseSeverity(event && (event.severity || event.level || event.status));
          const badge = document.createElement('span');
          badge.className = 'pipeline-event-badge';
          badge.dataset.state = severity;
          badge.textContent = severity;
          entry.appendChild(badge);

          const body = document.createElement('div');
          body.className = 'pipeline-event-body';
          const message =
            (event && (event.message || event.detail || event.description || event.status)) || 'Pipeline event';
          const messageEl = document.createElement('p');
          messageEl.className = 'pipeline-event-message';
          messageEl.textContent = message;
          body.appendChild(messageEl);

          const timestamp = formatTimestamp(event && event.timestamp);
          if (timestamp) {
            const meta = document.createElement('span');
            meta.className = 'pipeline-event-meta';
            meta.textContent = timestamp;
            body.appendChild(meta);
          }
          runList.appendChild(entry);
          entry.appendChild(body);
        });

        item.appendChild(runList);
        list.appendChild(item);
      });
      section.hidden = runEntries.length === 0;
    };

    const setRunStatus = (card, message, state) => {
      const status = card.querySelector('[data-pipeline-run-status]');
      if (!status) {
        return;
      }
      status.textContent = message || '';
      if (state) {
        status.dataset.state = state;
      } else {
        delete status.dataset.state;
      }
    };

    const refreshRun = async (card, runId) => {
      if (!runId) {
        return;
      }
      const refreshButton = card.querySelector('[data-pipeline-refresh-run]');
      if (refreshButton) {
        refreshButton.disabled = true;
      }
      setRunStatus(card, 'Refreshing status…', 'running');
      try {
        const encodedId = encodeURIComponent(runId);
        const [run, events] = await Promise.all([
        requestJson(`/api/pipelines/runs/${encodedId}`),
        requestJson(`/api/pipelines/runs/${encodedId}/events`),
        ]);
        const statusText = run && typeof run.status === 'string' ? run.status : 'unknown';
        const normalised = statusText.toLowerCase();
        const state = normalised.includes('fail') || normalised.includes('error')
        ? 'error'
        : normalised === 'succeeded'
          ? 'success'
          : 'running';
        setRunStatus(card, `Status: ${statusText}`, state);
        renderEvents(card, events);
        card.dataset.lastRunId = runId;
        if (refreshButton) {
        refreshButton.hidden = false;
        }
      } catch (error) {
        setRunStatus(card, error && error.message ? error.message : 'Unable to load run status.', 'error');
        throw error;
      } finally {
        if (refreshButton) {
        refreshButton.disabled = false;
        }
      }
    };

    const renderParameters = (definition, container) => {
      if (!container) {
        return [];
      }
      container.innerHTML = '';
      const parameters = definition && typeof definition.parameters === 'object' && !Array.isArray(definition.parameters)
        ? definition.parameters
        : {};
      const names = Object.keys(parameters || {})
        .filter((name) => typeof name === 'string' && name.length > 0)
        .sort();
      if (!names.length) {
        const placeholder = document.createElement('p');
        placeholder.className = 'pipeline-param-empty';
        placeholder.textContent = 'No parameters required.';
        container.appendChild(placeholder);
        return [];
      }
      names.forEach((name) => {
        const field = document.createElement('div');
        field.className = 'pipeline-param-field';
        const label = document.createElement('label');
        label.setAttribute('for', `${definition.name}-${name}-input`);
        label.textContent = name;
        const input = document.createElement('input');
        input.id = `${definition.name}-${name}-input`;
        input.name = name;
        input.type = 'text';
        const schema = parameters[name];
        const schemaIsObject = Boolean(
        schema && typeof schema === 'object' && Array.isArray(schema) === false,
        );
        const defaultValue = schemaIsObject && Object.prototype.hasOwnProperty.call(schema, 'default')
        ? schema.default
        : schema;
        const required = schemaIsObject && Boolean(schema.required);
        const description = schemaIsObject && typeof schema.description === 'string'
        ? schema.description
        : '';
        let defaultDisplay = '';
        if (typeof defaultValue === 'string') {
        defaultDisplay = defaultValue;
        } else if (defaultValue !== undefined && defaultValue !== null) {
        try {
          defaultDisplay = JSON.stringify(defaultValue);
        } catch (error) {
          defaultDisplay = String(defaultValue);
        }
        }
        if (defaultDisplay) {
        input.placeholder = defaultDisplay;
        } else if (required) {
        input.placeholder = 'Required parameter';
        } else {
        input.placeholder = 'Optional parameter';
        }
        input.required = required;
        field.appendChild(label);
        field.appendChild(input);
        if (defaultDisplay) {
        const hint = document.createElement('span');
        hint.className = 'pipeline-param-default';
        hint.textContent = `Default: ${defaultDisplay}`;
        field.appendChild(hint);
        }
        if (description) {
        const help = document.createElement('span');
        help.className = 'pipeline-param-description';
        help.textContent = description;
        field.appendChild(help);
        }
        container.appendChild(field);
      });
      return names;
    };

    const attachRunHandlers = (card, definition, parameterNames) => {
      const form = card.querySelector('[data-pipeline-form]');
      const refreshButton = card.querySelector('[data-pipeline-refresh-run]');
      if (!form) {
        return;
      }
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const runButton = card.querySelector('[data-pipeline-run]');
        if (runButton) {
        runButton.disabled = true;
        }
        setRunStatus(card, 'Triggering pipeline…', 'running');
        try {
        const formData = new FormData(form);
        const parameters = {};
        parameterNames.forEach((name) => {
          const value = formData.get(name);
          if (typeof value === 'string') {
          const trimmed = value.trim();
          if (trimmed) {
            parameters[name] = trimmed;
          }
          }
        });
        const payload = { parameters };
        const run = await requestJson(`/api/pipelines/${encodeURIComponent(definition.name)}/runs`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        const runId = run && run.id ? run.id : '';
        if (runId) {
          setRunStatus(card, `Triggered run ${runId}`, 'info');
          await refreshRun(card, runId);
        } else {
          setRunStatus(card, 'Pipeline triggered.', 'success');
        }
        } catch (error) {
        if (error && error.code === NO_CREDENTIALS_CODE) {
          setRunStatus(card, 'Add Trafalgar credentials to run pipelines.', 'error');
        } else {
          setRunStatus(card, error && error.message ? error.message : 'Unable to trigger pipeline.', 'error');
        }
        } finally {
        const runButton = card.querySelector('[data-pipeline-run]');
        if (runButton) {
          runButton.disabled = false;
        }
        }
      });
      if (refreshButton) {
        refreshButton.addEventListener('click', (event) => {
        event.preventDefault();
        const runId = card.dataset.lastRunId || refreshButton.dataset.runId || '';
        if (!runId) {
          return;
        }
        refreshRun(card, runId).catch((error) => {
          console.error('pipeline.refresh.failed', error);
        });
        });
      }
    };

    const buildCard = (definition) => {
      const fragment = template.content.cloneNode(true);
      const card = fragment.querySelector('[data-pipeline-card]');
      if (!card) {
        return null;
      }
      const identifier = definition && definition.name ? definition.name : '';
      const displayName = (definition && (definition.display_name || definition.name)) || 'Pipeline';
      const statusValue = normaliseStatus(
        definition && (definition.status || definition.state || definition.pipeline_status),
      ) || 'unknown';
      card.dataset.identifier = identifier;
      card.dataset.name = identifier;
      card.dataset.displayName = displayName;
      card.dataset.status = statusValue;
      const nameElement = card.querySelector('[data-pipeline-name]');
      if (nameElement) {
        nameElement.textContent = displayName;
      }
      const identifierElement = card.querySelector('[data-pipeline-identifier]');
      if (identifierElement) {
        identifierElement.textContent = identifier;
      }
      const statusElement = card.querySelector('[data-pipeline-status-text]');
      if (statusElement) {
        statusElement.textContent = statusValue === 'unknown' ? 'Status: Unknown' : `Status: ${statusValue}`;
        statusElement.dataset.state = statusValue;
      }
      const descriptionElement = card.querySelector('[data-pipeline-description]');
      const description = definition && typeof definition.description === 'string'
        ? definition.description.trim()
        : '';
      if (descriptionElement) {
        if (description) {
          descriptionElement.textContent = description;
        } else {
          descriptionElement.remove();
        }
      }
      const parametersContainer = card.querySelector('[data-pipeline-parameters]');
      const parameterNames = renderParameters(definition, parametersContainer);
      return { card, parameterNames };
    };

    const renderPipelines = (pipelines) => {
      cardsContainer.innerHTML = '';
      pipelinesCache = Array.isArray(pipelines) ? pipelines.slice() : [];
      pipelinesCache.forEach((definition) => {
        const built = buildCard(definition);
        if (!built) {
          return;
        }
        attachRunHandlers(built.card, definition, built.parameterNames);
        cardsContainer.appendChild(built.card);
      });
      renderStatusFilters(pipelinesCache);
      applyPipelineFilters();
    };

    const loadPipelines = async () => {
      if (loading) {
        return;
      }
      loading = true;
      setStatus('Loading pipelines…', 'running');
      showError('');
      try {
        const pipelines = await requestJson('/api/pipelines');
        renderPipelines(pipelines);
        const total = Array.isArray(pipelines) ? pipelines.length : 0;
        setStatus(
        total ? `Loaded ${total} pipeline${total === 1 ? '' : 's'}.` : 'No pipelines registered.',
        total ? 'success' : 'info',
        );
        loaded = true;
      } catch (error) {
        loaded = false;
        if (error && error.code === NO_CREDENTIALS_CODE) {
        setStatus('Add Trafalgar credentials to load pipelines.', 'info');
        showError('Authentication is required to load pipelines.');
        renderPipelines([]);
        } else {
        const message = error && error.message ? error.message : 'Unable to load pipelines.';
        setStatus(message, 'error');
        showError(message);
        renderPipelines([]);
        }
      } finally {
        loading = false;
      }
    };

    const ensureLoaded = (force = false) => {
      if (loading) {
        return;
      }
      if (force) {
        loaded = false;
      }
      if (!loaded) {
        loadPipelines().catch((error) => {
        console.error('pipeline.load.unhandled', error);
        });
      }
    };

    if (refreshButton) {
      refreshButton.addEventListener('click', (event) => {
        event.preventDefault();
        ensureLoaded(true);
      });
    }

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        applyPipelineFilters();
      });
    }

    ensureLoaded();
    window.triggerPipelineRefresh = () => ensureLoaded(true);

    const observer = new MutationObserver(() => {
      if (pipelinePage.classList.contains('active')) {
        ensureLoaded();
      }
    });
    observer.observe(pipelinePage, { attributes: true, attributeFilter: ['class'] });
    })();

    (function setupDashboardCharts() {
    const chartCards = Array.from(document.querySelectorAll('#page-dashboard [data-chart-id]'));
    const chartInstances = new Map();
    const colourPalette = ['#60a5fa', '#34d399', '#fbbf24', '#f97316', '#a855f7', '#f472b6'];
    const pendingRefreshes = [];
    let chartsReady = false;

    const setCardState = (card, state, overrideMessage) => {
      const placeholder = card.querySelector('.chart-placeholder');
      const canvas = card.querySelector('canvas');
      if (placeholder) {
        if (state === 'ready') {
        placeholder.hidden = true;
        } else {
        placeholder.hidden = false;
        if (overrideMessage) {
          placeholder.textContent = overrideMessage;
        } else if (state === 'error') {
          placeholder.textContent = card.dataset.errorMessage || 'Unable to load data.';
        } else {
          placeholder.textContent = card.dataset.emptyMessage || 'No data available yet.';
        }
        }
      }
      if (canvas) {
        canvas.hidden = state !== 'ready';
      }
      card.classList.toggle('is-ready', state === 'ready');
      card.classList.toggle('is-error', state === 'error');
      card.classList.toggle('is-empty', state === 'empty');
    };

    const destroyChart = (id) => {
      const existing = chartInstances.get(id);
      if (existing) {
        existing.destroy();
        chartInstances.delete(id);
      }
    };

    const findCard = (id) => chartCards.find((element) => element.dataset.chartId === id);

    const createOrUpdateChart = (id, config) => {
      const card = findCard(id);
      if (!card) {
        return;
      }
      const canvas = card.querySelector('canvas');
      if (!canvas) {
        return;
      }
      if (!config) {
        destroyChart(id);
        setCardState(card, 'empty');
        return;
      }
      let chart = chartInstances.get(id);
      if (!chart) {
        chart = new Chart(canvas, config);
        chartInstances.set(id, chart);
      } else {
        chart.config.type = config.type;
        chart.options = config.options;
        chart.data.labels = config.data.labels;
        chart.data.datasets = config.data.datasets;
        chart.update();
      }
      setCardState(card, 'ready');
    };

    const normaliseWindowLabel = (label) => {
      const value = String(label || '').toLowerCase();
      switch (value) {
        case '1h':
        return 'Past hour';
        case '6h':
        return 'Past 6 hours';
        case '24h':
        return 'Past day';
        case '7d':
        return 'Past week';
        default:
        return label || 'Window';
      }
    };

    const buildStatusBreakdownConfig = (statuses) => {
      const entries = Object.entries(statuses || {})
        .map(([key, value]) => {
        const record = value && typeof value === 'object' ? value : { count: value };
        const count = Number(record.count);
        return {
          label: key || 'unknown',
          value: Number.isFinite(count) ? count : 0,
        };
        })
        .filter((entry) => entry.value > 0)
        .sort((left, right) => left.label.localeCompare(right.label));
      if (!entries.length) {
        return null;
      }
      const labels = entries.map((entry) => entry.label);
      const data = entries.map((entry) => entry.value);
      const colours = labels.map((_, index) => colourPalette[index % colourPalette.length]);
      return {
        type: 'doughnut',
        data: {
        labels,
        datasets: [
          {
          label: 'Render jobs',
          data,
          backgroundColor: colours,
          borderColor: '#0f172a',
          borderWidth: 1,
          },
        ],
        },
        options: {
        responsive: true,
        plugins: {
          legend: {
          position: 'bottom',
          labels: { color: '#cbd5f5' },
          },
        },
        },
      };
    };

    const buildThroughputConfig = (windows) => {
      const keys = Object.keys(windows || {});
      const entries = keys
        .map((key) => {
        const record = windows ? windows[key] : null;
        const total =
          record && typeof record === 'object'
          ? Number(record.total_jobs ?? record)
          : Number(record);
        return {
          label: normaliseWindowLabel(key),
          value: Number.isFinite(total) ? total : 0,
        };
        })
        .filter((entry) => entry.value > 0);
      if (!entries.length) {
        return null;
      }
      const labels = entries.map((entry) => entry.label);
      const data = entries.map((entry) => entry.value);
      return {
        type: 'line',
        data: {
        labels,
        datasets: [
          {
          label: 'Jobs submitted',
          data,
          borderColor: '#60a5fa',
          backgroundColor: 'rgba(96, 165, 250, 0.25)',
          tension: 0.35,
          fill: true,
          pointBackgroundColor: '#2563eb',
          pointRadius: 4,
          },
        ],
        },
        options: {
        responsive: true,
        scales: {
          x: {
          ticks: { color: '#cbd5f5' },
          grid: { color: 'rgba(148, 163, 184, 0.2)' },
          },
          y: {
          beginAtZero: true,
          ticks: { color: '#cbd5f5', precision: 0 },
          grid: { color: 'rgba(148, 163, 184, 0.2)' },
          },
        },
        plugins: {
          legend: { display: false },
        },
        },
      };
    };

    const buildAdapterUtilisationConfig = (adapters) => {
      const entries = Object.entries(adapters || {})
        .map(([key, value]) => {
        const record = value && typeof value === 'object' ? value : { total_jobs: value };
        const total = Number(record.total_jobs);
        return {
          label: key || 'unknown',
          value: Number.isFinite(total) ? total : 0,
        };
        })
        .filter((entry) => entry.value > 0)
        .sort((left, right) => right.value - left.value);
      if (!entries.length) {
        return null;
      }
      const labels = entries.map((entry) => entry.label);
      const data = entries.map((entry) => entry.value);
      const colours = labels.map((_, index) => colourPalette[(index + 1) % colourPalette.length]);
      return {
        type: 'bar',
        data: {
        labels,
        datasets: [
          {
          label: 'Jobs',
          data,
          backgroundColor: colours,
          borderRadius: 10,
          },
        ],
        },
        options: {
        indexAxis: 'y',
        responsive: true,
        scales: {
          x: {
          beginAtZero: true,
          ticks: { color: '#cbd5f5', precision: 0 },
          grid: { color: 'rgba(148, 163, 184, 0.18)' },
          },
          y: {
          ticks: { color: '#cbd5f5' },
          grid: { display: false },
          },
        },
        plugins: {
          legend: { display: false },
        },
        },
      };
    };

    window.utaDashboardTestHooks = {
      buildStatusBreakdownConfig,
      buildThroughputConfig,
      buildAdapterUtilisationConfig,
      normaliseWindowLabel,
    };

    if (!chartCards.length) {
      window.triggerDashboardRefresh = () => {};
      return;
    }

    chartCards.forEach((card) => setCardState(card, 'empty'));

    const refreshCharts = async () => {
      const hasCredentials = Boolean(dashboardCredentials.bearerToken || dashboardCredentials.apiKey);
      if (!hasCredentials) {
        chartInstances.forEach((chart) => chart.destroy());
        chartInstances.clear();
        updateAuthCardState();
        chartCards.forEach((card) => {
        card.classList.remove('is-loading');
        setCardState(card, 'empty', requireCredentialsMessage);
        });
        return;
      }
      const metricsUrl = joinWithRoot('/render/jobs/metrics');
      const headers = resolveDashboardHeaders();
      const options = { credentials: 'same-origin' };
      if (headers) {
        options.headers = headers;
      }
      chartCards.forEach((card) => card.classList.add('is-loading'));
      try {
        const response = await fetch(metricsUrl, options);
        if ([401, 403, 503].includes(response.status)) {
        updateAuthCardState('error');
        chartCards.forEach((card) => {
          setCardState(card, 'error', authFailureMessage);
        });
        return;
        }
        if (!response.ok) {
        throw new Error(`Failed to load render analytics (${response.status})`);
        }
        const payload = await response.json();
        const statuses = payload ? payload.statuses : null;
        const windows = payload ? payload.submission_windows : null;
        const adapters = payload ? payload.adapters : null;
        createOrUpdateChart('render-status', buildStatusBreakdownConfig(statuses));
        createOrUpdateChart('render-throughput', buildThroughputConfig(windows));
        createOrUpdateChart('render-adapters', buildAdapterUtilisationConfig(adapters));
        updateAuthCardState();
      } catch (error) {
        console.error('dashboard.refresh.failed', error);
        updateAuthCardState('error');
        chartCards.forEach((card) => {
        setCardState(card, 'error', card.dataset.errorMessage || 'Unable to load data.');
        });
      } finally {
        chartCards.forEach((card) => card.classList.remove('is-loading'));
      }
    };

    const runRefresh = () => {
      refreshCharts().catch((error) => {
        console.error('dashboard.refresh.unhandled', error);
      });
    };

    window.triggerDashboardRefresh = () => {
      if (chartsReady) {
        runRefresh();
      } else {
        pendingRefreshes.push(runRefresh);
      }
    };

    const chartScript = document.getElementById('uta-dashboard-chartjs');
    const markReady = () => {
      if (chartsReady || typeof window.Chart !== 'function') {
        return;
      }
      chartsReady = true;
      window.triggerDashboardRefresh = runRefresh;
      pendingRefreshes.splice(0).forEach((fn) => fn());
    };

    if (typeof window.Chart === 'function') {
      markReady();
    } else if (chartScript) {
      chartScript.addEventListener('load', markReady, { once: true });
      chartScript.addEventListener(
        'error',
        () => {
        chartsReady = true;
        window.triggerDashboardRefresh = () => {};
        updateAuthCardState('error');
        chartCards.forEach((card) => {
          card.classList.remove('is-loading');
          setCardState(card, 'error', card.dataset.errorMessage || 'Unable to load data.');
        });
        pendingRefreshes.length = 0;
        },
        { once: true },
      );
    } else {
      document.addEventListener('DOMContentLoaded', markReady, { once: true });
    }
    })();

    const dashboardPage = document.getElementById('page-dashboard');
    if (dashboardPage && dashboardPage.classList.contains('active') && typeof window.triggerDashboardRefresh === 'function') {
    window.triggerDashboardRefresh();
    }
