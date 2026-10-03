/* Scale Culture NZ — storefront behaviour. No dependencies, progressive enhancement only. */
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const store = {
    get(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
      } catch (e) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(key, JSON.stringify(value));
      } catch (e) {
        /* storage unavailable (private mode) — feature degrades silently */
      }
    }
  };

  /* Search overlay */
  const overlay = $('#SearchOverlay');
  if (overlay) {
    $$('[data-search-open]').forEach((el) =>
      el.addEventListener('click', (e) => {
        e.preventDefault();
        overlay.classList.add('is-open');
        $('input[type="search"]', overlay).focus();
      })
    );
    $$('[data-search-close]', overlay).forEach((el) =>
      el.addEventListener('click', () => overlay.classList.remove('is-open'))
    );
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') overlay.classList.remove('is-open');
    });
  }

  /* Quantity steppers (product page) */
  $$('[data-qty]').forEach((btn) =>
    btn.addEventListener('click', () => {
      const input = $('input', btn.parentElement);
      const max = input.max ? parseInt(input.max, 10) : Infinity;
      const next = Math.min(max, Math.max(1, (parseInt(input.value, 10) || 1) + parseInt(btn.dataset.qty, 10)));
      input.value = next;
    })
  );

  /* Cart quantity steppers: change then submit the cart form to update */
  $$('[data-cart-qty]').forEach((btn) =>
    btn.addEventListener('click', () => {
      const input = $('input', btn.parentElement);
      input.value = Math.max(0, (parseInt(input.value, 10) || 0) + parseInt(btn.dataset.delta, 10));
      const form = btn.closest('form');
      if (form) form.submit();
    })
  );

  /* Variant select: reload so stock state / pre-order info render server-side */
  const variantSelect = $('[data-variant-select]');
  if (variantSelect) {
    variantSelect.addEventListener('change', () => {
      const url = new URL(window.location.href);
      url.searchParams.set('variant', variantSelect.value);
      window.location.href = url.toString();
    });
  }

  /* Sticky mobile add-to-cart: show once the main buy button scrolls out of view */
  const sticky = $('[data-sticky-atc]');
  const addButton = $('[data-add-button]');
  if (sticky && addButton && 'IntersectionObserver' in window) {
    new IntersectionObserver(([entry]) => {
      const show = !entry.isIntersecting && entry.boundingClientRect.top < 0;
      sticky.classList.toggle('is-visible', show);
      sticky.setAttribute('aria-hidden', String(!show));
    }).observe(addButton);
  }

  /* Drop countdowns */
  $$('[data-countdown]').forEach((el) => {
    const target = new Date(el.dataset.countdown.replace(/([+-]\d{2})(\d{2})$/, '$1:$2')).getTime();
    if (Number.isNaN(target)) return;
    const units = { d: 86400000, h: 3600000, m: 60000, s: 1000 };
    const tick = () => {
      let diff = target - Date.now();
      if (diff <= 0) {
        el.hidden = true;
        return clearInterval(timer);
      }
      Object.entries(units).forEach(([unit, ms]) => {
        const value = Math.floor(diff / ms);
        diff -= value * ms;
        const node = $(`[data-unit="${unit}"]`, el);
        if (node) node.textContent = String(value).padStart(2, '0');
      });
    };
    const timer = setInterval(tick, 1000);
    tick();
  });

  /* Filters: drawer on mobile, auto-apply on desktop */
  const facets = $('[data-facets]');
  if (facets) {
    const desktop = window.matchMedia('(min-width: 990px)');
    const submit = () => {
      const params = new URLSearchParams(new FormData(facets));
      for (const [key, value] of Array.from(params.entries())) if (value === '') params.delete(key);
      window.location.search = params.toString();
    };
    $$('[data-facets-open]').forEach((b) =>
      b.addEventListener('click', () => {
        facets.classList.add('is-open');
        document.body.style.overflow = 'hidden';
      })
    );
    $$('[data-facets-close]', facets).forEach((b) =>
      b.addEventListener('click', () => {
        facets.classList.remove('is-open');
        document.body.style.overflow = '';
        if (b.classList.contains('button')) submit();
      })
    );
    facets.addEventListener('change', () => {
      if (desktop.matches) submit();
    });
    facets.addEventListener('submit', (e) => {
      e.preventDefault();
      submit();
    });
    $$('[data-sort]').forEach((s) => s.addEventListener('change', submit));
  }

  /* Card fetcher used by wishlist + recently viewed */
  const fetchCards = async (handles, grid) => {
    const html = await Promise.all(
      handles.map((h) =>
        fetch(`/products/${encodeURIComponent(h)}?view=card`)
          .then((r) => (r.ok ? r.text() : ''))
          .catch(() => '')
      )
    );
    grid.innerHTML = html
      .filter(Boolean)
      .map((h) => `<li>${h}</li>`)
      .join('');
    bindWishlist(grid);
    return grid.children.length;
  };

  /* Collector service (Phase 2) — reached through the Shopify app proxy, which signs
     each request with the logged-in customer id. */
  const ctx = window.ScaleCulture || {};
  const collector = ctx.collector || {};
  const collectorOn = Boolean(collector.enabled && collector.loggedIn);
  const api = async (path, body) => {
    const res = await fetch(`${collector.proxy}${path}`, {
      method: body ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      credentials: 'same-origin',
      body: body ? JSON.stringify(body) : undefined
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  };

  /* Wishlist: browser storage for guests, synced to the account for logged-in collectors */
  const WISHLIST_KEY = 'sc:wishlist';
  const getWishlist = () => store.get(WISHLIST_KEY, []);
  const renderWishlistState = () => {
    const list = getWishlist();
    $$('[data-wishlist-toggle]').forEach((btn) => {
      const on = list.includes(btn.dataset.wishlistToggle);
      btn.setAttribute('aria-pressed', String(on));
      const label = $('[data-wishlist-label]', btn);
      if (label) label.textContent = on ? 'Saved to wishlist' : 'Add to wishlist';
    });
    $$('[data-wishlist-count]').forEach((el) => {
      el.textContent = list.length;
      el.hidden = list.length === 0;
    });
  };
  function bindWishlist(root = document) {
    $$('[data-wishlist-toggle]', root).forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const handle = btn.dataset.wishlistToggle;
        const list = getWishlist();
        const next = list.includes(handle) ? list.filter((h) => h !== handle) : [handle, ...list];
        store.set(WISHLIST_KEY, next);
        renderWishlistState();
        if (collectorOn) {
          api('/wishlist', { handle, product_id: btn.dataset.productId, saved: next.includes(handle) }).catch(() => {});
        }
        document.dispatchEvent(new CustomEvent('wishlist:change', { detail: { handle, saved: next.includes(handle) } }));
      });
    });
    renderWishlistState();
  }
  bindWishlist();

  if (collectorOn && Array.isArray(collector.wishlist)) {
    const local = getWishlist();
    const merged = [...new Set([...collector.wishlist, ...local])];
    store.set(WISHLIST_KEY, merged);
    renderWishlistState();
    if (local.some((h) => !collector.wishlist.includes(h))) {
      api('/wishlist', { merge: local }).catch(() => {});
    }
  }

  const wishlistGrid = $('[data-wishlist-grid]');
  if (wishlistGrid) {
    const handles = getWishlist();
    const empty = $('[data-wishlist-empty]');
    if (handles.length) {
      fetchCards(handles.slice(0, 48), wishlistGrid).then((n) => {
        if (empty) empty.hidden = n > 0;
      });
    }
  }

  /* Recently viewed */
  const RECENT_KEY = 'sc:recent';
  const current = $('[data-recently-viewed-product]');
  const currentHandle = current ? JSON.parse(current.textContent) : null;
  const recent = store.get(RECENT_KEY, []).filter((h) => h !== currentHandle);
  const recentSection = $('[data-recently-viewed]');
  if (recentSection && recent.length) {
    fetchCards(recent.slice(0, 4), $('[data-recently-viewed-grid]', recentSection)).then((n) => {
      recentSection.hidden = n === 0;
    });
  }
  if (currentHandle) store.set(RECENT_KEY, [currentHandle, ...recent].slice(0, 12));

  /* Drop alerts: fold selected interests into customer tags */
  $$('form.interest-form').forEach((form) => {
    form.addEventListener('submit', () => {
      const tagsInput = $('[data-interest-tags]', form);
      const picked = $$('input[type="checkbox"]:checked', form).map((c) => c.value);
      tagsInput.value = ['newsletter', 'drop-alerts', ...picked].join(',');
    });
  });

  /* Lazy product recommendations */
  $$('[data-recommendations]').forEach((section) => {
    if (section.children.length) return;
    fetch(section.dataset.url)
      .then((r) => r.text())
      .then((text) => {
        const doc = new DOMParser().parseFromString(text, 'text/html');
        const fresh = doc.querySelector('[data-recommendations]');
        if (fresh && fresh.innerHTML.trim()) {
          section.innerHTML = fresh.innerHTML;
          bindWishlist(section);
        }
      })
      .catch(() => {});
  });

  /* My Garage: Owned / Wanted / Pre-ordered toggles (product page) */
  $$('[data-garage-control]').forEach((control) => {
    const productId = control.dataset.productId;
    const buttons = $$('[data-garage-status]', control);
    buttons.forEach((btn) =>
      btn.addEventListener('click', async () => {
        const active = btn.getAttribute('aria-pressed') === 'true';
        const status = active ? null : btn.dataset.garageStatus;
        buttons.forEach((b) => (b.disabled = true));
        try {
          await api('/garage', { product_id: productId, status });
          buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.garageStatus === status)));
          const link = $('[data-garage-link]', control);
          if (link) link.hidden = !status;
        } catch (e) {
          window.alert(e.message);
        } finally {
          buttons.forEach((b) => (b.disabled = false));
        }
      })
    );
    const select = $('[data-garage-select]', control);
    if (select) {
      select.addEventListener('change', async () => {
        select.disabled = true;
        try {
          await api('/garage', { product_id: productId, status: select.value || null });
          window.location.reload();
        } catch (e) {
          window.alert(e.message);
          select.disabled = false;
        }
      });
    }
  });

  /* My Garage page: status tabs */
  const tabs = $('[data-garage-tabs]');
  if (tabs) {
    tabs.addEventListener('click', (e) => {
      const tab = e.target.closest('[data-filter]');
      if (!tab) return;
      $$('[data-filter]', tabs).forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
      $$('[data-garage-item]').forEach((item) => {
        item.hidden = tab.dataset.filter !== 'all' && item.dataset.status !== tab.dataset.filter;
      });
    });
  }

  /* Collector profile */
  const profileForm = $('[data-profile-form]');
  if (profileForm) {
    profileForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = new FormData(profileForm);
      const status = $('[data-profile-status]', profileForm);
      const body = {
        display_name: f.get('display_name'),
        location: f.get('location'),
        bio: f.get('bio'),
        public: f.has('public'),
        show_wanted: f.has('show_wanted'),
        auto_garage: f.has('auto_garage'),
        interests: {
          makes: f.getAll('makes'),
          scales: f.getAll('scales'),
          brands: f.getAll('brands'),
          categories: f.getAll('categories')
        }
      };
      status.textContent = 'Saving…';
      try {
        const res = await api('/profile', body);
        status.textContent = 'Saved.';
        const link = $('[data-profile-public-link]', profileForm);
        if (link) {
          link.hidden = !res.url;
          if (res.url) link.href = res.url;
        }
      } catch (err) {
        status.textContent = err.message;
      }
    });
  }

  /* Klaviyo client API: restock alerts + drop reminders (public site key only) */
  const klaviyo = async (endpoint, data) => {
    const res = await fetch(`https://a.klaviyo.com/client/${endpoint}/?company_id=${encodeURIComponent(ctx.klaviyo)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/vnd.api+json', revision: '2024-10-15' },
      body: JSON.stringify({ data })
    });
    if (!res.ok) throw new Error('Something went wrong — please try again.');
  };
  const profileRef = (email) => ({ data: { type: 'profile', attributes: { email } } });

  $$('[data-restock-form]').forEach((form) =>
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = $('[data-restock-status]', form);
      try {
        await klaviyo('back-in-stock-subscriptions', {
          type: 'back-in-stock-subscription',
          attributes: { channels: ['EMAIL'], profile: profileRef(form.email.value) },
          relationships: { variant: { data: { type: 'catalog-variant', id: `$shopify:::$default:::${form.dataset.variantId}` } } }
        });
        status.textContent = "You're on the list — we'll email you when it's available.";
        form.querySelector('button').disabled = true;
      } catch (err) {
        status.textContent = err.message;
      }
    })
  );

  $$('[data-drop-reminder]').forEach((form) =>
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = $('[data-restock-status]', form);
      const d = form.dataset;
      try {
        await klaviyo('events', {
          type: 'event',
          attributes: {
            properties: { drop_name: d.dropName, drop_handle: d.dropHandle, release_date: d.dropDate, brands: d.dropBrands, url: d.dropUrl },
            metric: { data: { type: 'metric', attributes: { name: 'Drop Reminder Requested' } } },
            profile: profileRef(form.email.value)
          }
        });
        status.textContent = "Reminder set — we'll email you when the drop goes live.";
        form.querySelector('button').disabled = true;
      } catch (err) {
        status.textContent = err.message;
      }
    })
  );
})();
