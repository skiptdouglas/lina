// Sample catalogue for the static preview. Shapes mirror the Shopify Liquid objects
// the theme reads (product, collection, metafields, metaobjects, article, customer).

const DAY = 86400000;
const NOW = Date.now();
const ago = (d) => new Date(NOW - d * DAY).toISOString();

// Generated product "photos": studio-style SVGs of a car silhouette in the model's colour.
export function carSvg({ colour, label, sub, bg = '#e9eaea', view = 'front' }) {
  const flip = view === 'rear' ? 'scale(-1,1) translate(-800,0)' : '';
  const box = view === 'box';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800">
  <defs>
    <radialGradient id="g" cx="50%" cy="45%" r="70%"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="${bg}"/></radialGradient>
    <linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${colour}" stop-opacity=".95"/><stop offset="1" stop-color="${colour}" stop-opacity=".7"/></linearGradient>
  </defs>
  <rect width="800" height="800" fill="url(#g)"/>
  ${box ? `<rect x="130" y="210" width="540" height="380" rx="6" fill="#111"/><rect x="150" y="230" width="500" height="250" fill="url(#g)" opacity=".9"/><rect x="130" y="500" width="540" height="10" fill="#d7262e"/><text x="400" y="555" font-family="Arial Narrow,Arial" font-weight="700" font-size="34" fill="#fff" text-anchor="middle" letter-spacing="3">${label}</text>` : ''}
  <g transform="${flip} ${box ? 'translate(120,150) scale(.7)' : ''}">
    <ellipse cx="400" cy="560" rx="300" ry="26" fill="#000" opacity=".18"/>
    <path d="M120 500 L150 440 Q170 410 230 400 L300 352 Q330 332 380 330 L520 330 Q560 332 590 362 L640 405 Q690 412 700 440 L712 500 Q712 520 690 522 L140 522 Q118 520 120 500Z" fill="url(#b)"/>
    <path d="M318 360 L380 342 L470 342 L470 400 L290 400Z M490 342 L520 342 Q548 346 575 372 L600 400 L490 400Z" fill="#1c1d1f" opacity=".85"/>
    <rect x="128" y="470" width="40" height="12" rx="3" fill="#f6f2d0"/><rect x="664" y="468" width="38" height="12" rx="3" fill="#d7262e"/>
    <circle cx="245" cy="522" r="54" fill="#111"/><circle cx="245" cy="522" r="30" fill="#9a9da1"/><circle cx="245" cy="522" r="8" fill="#333"/>
    <circle cx="590" cy="522" r="54" fill="#111"/><circle cx="590" cy="522" r="30" fill="#9a9da1"/><circle cx="590" cy="522" r="8" fill="#333"/>
  </g>
  ${box ? '' : `<text x="40" y="760" font-family="Arial" font-size="22" fill="#8a8d91" letter-spacing="2">${sub || ''}</text>`}
</svg>`;
}

export function heroSvg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1200">
  <defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b1c1f"/><stop offset=".6" stop-color="#0b0b0c"/></linearGradient>
  <linearGradient id="c" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#3b2a6b"/><stop offset="1" stop-color="#5a3f9e"/></linearGradient>
  <radialGradient id="l" cx="70%" cy="55%" r="50%"><stop offset="0" stop-color="#d7262e" stop-opacity=".35"/><stop offset="1" stop-color="#d7262e" stop-opacity="0"/></radialGradient></defs>
  <rect width="2400" height="1200" fill="url(#s)"/><rect width="2400" height="1200" fill="url(#l)"/>
  ${Array.from({ length: 14 }, (_, i) => `<rect x="${i * 180 - 40}" y="930" width="110" height="6" fill="#2e3033"/>`).join('')}
  <g transform="translate(1050,330) scale(1.6)">
    <ellipse cx="400" cy="560" rx="320" ry="24" fill="#000" opacity=".6"/>
    <path d="M120 500 L150 440 Q170 410 230 400 L300 352 Q330 332 380 330 L520 330 Q560 332 590 362 L640 405 Q690 412 700 440 L712 500 Q712 520 690 522 L140 522 Q118 520 120 500Z" fill="url(#c)"/>
    <path d="M318 360 L380 342 L470 342 L470 400 L290 400Z M490 342 L520 342 Q548 346 575 372 L600 400 L490 400Z" fill="#0b0b0c" opacity=".9"/>
    <rect x="128" y="470" width="40" height="12" rx="3" fill="#fff8d6"/><rect x="664" y="468" width="38" height="12" rx="3" fill="#ff3b44"/>
    <circle cx="245" cy="522" r="54" fill="#050505"/><circle cx="245" cy="522" r="32" fill="#6d7075"/>
    <circle cx="590" cy="522" r="54" fill="#050505"/><circle cx="590" cy="522" r="32" fill="#6d7075"/>
  </g>
</svg>`;
}

const P = [
  ['inno64-r34-midnight-purple', 'INNO64', 'Nissan Skyline GT-R R34 V-Spec', 'Midnight Purple', '1:64', 'Nissan', 'Skyline', 'R34', 4995, 6, 'auto', '#4a2f86', 2],
  ['minigt-nsx-type-r-white', 'MINI GT', 'Honda NSX Type R', 'Championship White', '1:64', 'Honda', 'NSX', 'NA2', 2495, 2, 'auto', '#f2f1ec', 5],
  ['kaido-house-510-wagon', 'Kaido House', 'Datsun 510 Wagon Kaido', 'Green', '1:64', 'Datsun', '510', '', 5995, 0, 'auto', '#3f6b4a', 40],
  ['poprace-a80-rocket-bunny', 'POP RACE', 'Toyota Supra A80 Rocket Bunny', 'White', '1:64', 'Toyota', 'Supra', 'A80', 5495, 24, 'preorder', '#e9e9e4', 1],
  ['tarmac-911-gt3r-hong-kong', 'Tarmac Works', 'Porsche 911 GT3 R', 'Macau GP', '1:64', 'Porsche', '911', '992', 4495, 8, 'auto', '#e2b100', 9],
  ['inno64-fd3s-re-amemiya', 'INNO64', 'Mazda RX-7 FD3S RE Amemiya', 'Yellow', '1:64', 'Mazda', 'RX-7', 'FD3S', 5295, 3, 'auto', '#f0c419', 3],
  ['tlv-skyline-kpgc10', 'Tomica Limited Vintage', 'Nissan Skyline 2000GT-R KPGC10', 'Silver', '1:64', 'Nissan', 'Skyline', 'KPGC10', 6995, 0, 'coming_soon', '#b8bcc2', 0],
  ['aoshima-fd3s-kit', 'Aoshima', 'Mazda RX-7 FD3S Spirit R Kit', 'Kit', '1:24', 'Mazda', 'RX-7', 'FD3S', 6495, 8, 'auto', '#c3262e', 12],
  ['ignition-r34-z-tune', 'Ignition Model', 'Nissan Skyline GT-R R34 Nismo Z-Tune', 'Silver', '1:18', 'Nissan', 'Skyline', 'R34', 39995, 1, 'auto', '#9ea3a8', 20],
  ['minigt-lbwk-huracan', 'MINI GT', 'Lamborghini Huracán LB-Silhouette', 'Orange', '1:64', 'Lamborghini', 'Huracán', '', 2695, 14, 'auto', '#ef6a1f', 4],
  ['scale-culture-display-case-1-64', 'Scale Culture', '1:64 Acrylic Display Case', 'Single', '1:64', 'Other', 'Display case', '', 1495, 40, 'auto', '#9fb4c7', 30],
  ['scale-culture-garage-diorama-1-64', 'Scale Culture', '1:64 Garage Diorama', 'Workshop', '1:64', 'Other', 'Diorama', '', 3995, 12, 'auto', '#6b6f75', 30]
];
const ACCESSORIES = new Set(['scale-culture-display-case-1-64', 'scale-culture-garage-diorama-1-64']);

export const IMAGES = {};

function product([handle, vendor, vehicle, variant, scale, make, model, gen, price, qty, availability, colour, daysAgo], i) {
  const title = `${vendor} – ${vehicle} – ${variant} – ${scale}`;
  const media = ['front', 'rear', 'box'].map((view, j) => {
    const src = `img/${handle}-${view}.svg`;
    IMAGES[src] = carSvg({ colour, label: vendor.toUpperCase(), sub: `${vendor} · ${scale}`, view });
    return { src, alt: `${title} – ${view}`, width: 800, height: 800, aspect_ratio: 1 };
  });
  const variantObj = {
    id: 40000 + i,
    title: 'Default Title',
    sku: `${vendor.slice(0, 3).toUpperCase()}-${1000 + i}`,
    barcode: '',
    price,
    compare_at_price: handle === 'minigt-lbwk-huracan' ? 2995 : null,
    available: availability === 'preorder' ? true : availability === 'coming_soon' ? false : qty > 0,
    inventory_management: 'shopify',
    inventory_policy: availability === 'preorder' ? 'continue' : 'deny',
    inventory_quantity: qty,
    weight: 120
  };
  const meta = {
    scale: { value: scale },
    card_title: { value: vehicle },
    vehicle_make: { value: make },
    vehicle_model: { value: model },
    vehicle_generation: gen ? { value: gen } : null,
    availability: { value: availability },
    colour: { value: variant },
    vehicle_year: { value: 1999 },
    street_race: { value: 'Street' },
    country_of_origin: { value: 'Japan' },
    limited_edition: { value: handle.includes('kaido') || handle.includes('z-tune') },
    mpn: { value: `IN64-${1000 + i}` },
    wishlist_count: { value: handle.includes('kaido') ? 32 : i },
    // Drop-day limit on the hot INNO64 R34
    max_per_customer: handle === 'inno64-r34-midnight-purple' ? { value: 2 } : null,
    limit_until: handle === 'inno64-r34-midnight-purple' ? { value: new Date(NOW + 3 * DAY).toISOString().slice(0, 10) } : null,
    preorder_jp_release: availability === 'preorder' ? { value: 'November 2026' } : null,
    preorder_nz_arrival: availability === 'preorder' ? { value: 'December 2026' } : null,
    preorder_deposit: availability === 'preorder' ? { value: '$10' } : null,
    preorder_allocation: availability === 'preorder' ? { value: 40 } : null
  };
  for (const k of Object.keys(meta)) if (meta[k] === null) delete meta[k];
  const rating = i % 3 === 0 ? null : { rating: 4 + (i % 2) * 0.6, scale_max: 5 };
  return {
    id: 7000 + i,
    handle,
    title,
    vendor,
    type: ACCESSORIES.has(handle) ? 'Accessory' : scale === '1:24' ? 'Plastic Model Kit' : 'Die-cast',
    collections: ACCESSORIES.has(handle) ? [{ handle: 'display-cases' }] : [],
    url: `product-${handle}.html`,
    description: `<p>${vehicle} in ${variant}. Detailed ${scale} replica with rubber tyres, detailed lights and an acrylic display case. Imported direct from Japan.</p><p>Every Scale Culture order is packed in a rigid carton — boxes matter to collectors.</p>`,
    published_at: ago(daysAgo),
    featured_media: media[0],
    media,
    price,
    price_varies: false,
    available: variantObj.available,
    has_only_default_variant: true,
    options: ['Title'],
    variants: [variantObj],
    selected_or_first_available_variant: variantObj,
    metafields: {
      scale: meta,
      reviews: rating ? { rating: { value: rating }, rating_count: { value: 3 + i * 4 } } : {}
    }
  };
}

export const products = P.map(product);
const by = (h) => products.find((p) => p.handle === h);
const accessories = products.filter((p) => ACCESSORIES.has(p.handle));
by('inno64-r34-midnight-purple').metafields.scale.bundle_products = { value: accessories };
const models = products.filter((p) => !ACCESSORIES.has(p.handle));

const facet = (label, param, values) => ({
  label,
  type: 'list',
  active_values: values.filter((v) => v[2]).map(([l]) => ({ label: l, url_to_remove: '#' })),
  values: values.map(([l, count, active]) => ({ label: l, value: l, param_name: param, count, active: Boolean(active) }))
});

export function collection(handle, title, list, description = '') {
  return {
    handle,
    title,
    url: `collection-${handle}.html`,
    description,
    products: list,
    products_count: list.length,
    all_products_count: list.length,
    image: null,
    sort_by: 'created-descending',
    default_sort_by: 'created-descending',
    sort_options: [
      { value: 'created-descending', name: 'Newest' },
      { value: 'price-ascending', name: 'Price, low to high' },
      { value: 'price-descending', name: 'Price, high to low' },
      { value: 'best-selling', name: 'Best selling' }
    ],
    filters: [
      facet('Availability', 'filter.v.availability', [['In stock', 7, true], ['Out of stock', 3]]),
      { label: 'Price', type: 'price_range', active_values: [], range_max: 39995, min_value: { param_name: 'filter.v.price.gte', value: null }, max_value: { param_name: 'filter.v.price.lte', value: null } },
      facet('Brand', 'filter.p.vendor', [['INNO64', 3], ['MINI GT', 2], ['Kaido House', 1], ['POP RACE', 1], ['Tarmac Works', 1]]),
      facet('Scale', 'filter.p.m.scale.scale', [['1:64', 8, true], ['1:24', 1], ['1:18', 1]]),
      facet('Vehicle manufacturer', 'filter.p.m.scale.vehicle_make', [['Nissan', 3], ['Mazda', 2], ['Toyota', 1], ['Honda', 1], ['Porsche', 1]]),
      facet('Vehicle model', 'filter.p.m.scale.vehicle_model', [['Skyline', 3], ['RX-7', 2], ['Supra', 1], ['NSX', 1]]),
      facet('Release status', 'filter.p.m.scale.availability', [['auto', 8], ['preorder', 1], ['coming_soon', 1]])
    ],
    metafields: { scale: {} }
  };
}

export const collections = {
  'display-cases': collection('display-cases', 'Display Cases', accessories),
  'new-arrivals': collection('new-arrivals', 'New Arrivals', [...models].sort((a, b) => new Date(b.published_at) - new Date(a.published_at))),
  '1-64-diecast': collection('1-64-diecast', '1:64 Die-Cast', models.filter((p) => p.metafields.scale.scale.value === '1:64'), '<p>Premium 1:64 die-cast from INNO64, MINI GT, Kaido House, POP RACE and Tarmac Works — imported direct from Japan and Hong Kong.</p>'),
  'pre-orders': collection('pre-orders', 'Pre-Orders', [by('poprace-a80-rocket-bunny')]),
  'jdm-legends': collection('jdm-legends', 'JDM Legends', models.slice(0, 6)),
  'nissan-models': collection('nissan-models', 'Nissan Models', products.filter((p) => p.metafields.scale.vehicle_make.value === 'Nissan')),
  'toyota-models': collection('toyota-models', 'Toyota Models', [by('poprace-a80-rocket-bunny')]),
  'mazda-models': collection('mazda-models', 'Mazda Models', products.filter((p) => p.metafields.scale.vehicle_make.value === 'Mazda'))
};
for (const [h, t] of [['1-43-diecast', '1:43'], ['1-24', '1:24'], ['1-18-diecast', '1:18'], ['90s-japan', '90s Japan'], ['super-gt', 'Super GT'], ['liberty-walk', 'Liberty Walk']]) {
  collections[h] = collections[h] || collection(h, t, products.slice(2, 6));
}
for (const p of products) {
  const tile = `img/tile-${p.handle}.svg`;
  IMAGES[tile] = carSvg({ colour: p.media[0] && P.find((x) => x[0] === p.handle)[11], label: '', bg: '#2e3033' });
}
const tileImg = (h) => ({ src: `img/tile-${h}.svg`, alt: '', width: 800, height: 800 });
collections['1-64-diecast'].image = tileImg('inno64-r34-midnight-purple');
collections['1-43-diecast'].image = tileImg('tarmac-911-gt3r-hong-kong');
collections['1-24'].image = tileImg('aoshima-fd3s-kit');
collections['1-18-diecast'].image = tileImg('ignition-r34-z-tune');
collections['jdm-legends'].image = tileImg('inno64-fd3s-re-amemiya');
collections['90s-japan'].image = tileImg('minigt-nsx-type-r-white');
collections['super-gt'].image = tileImg('tarmac-911-gt3r-hong-kong');
collections['liberty-walk'].image = tileImg('minigt-lbwk-huracan');

IMAGES['img/hero.svg'] = heroSvg();
IMAGES['img/drop.svg'] = heroSvg().replace('#3b2a6b', '#8a1d22').replace('#5a3f9e', '#d7262e');

export const drop = {
  name: { value: 'Japan Drop #005' },
  brands: { value: ['INNO64', 'POP RACE', 'Aoshima'] },
  release_date: { value: new Date(NOW + 9 * DAY + 5 * 3600000).toISOString() },
  image: { value: { src: 'img/drop.svg', alt: '', width: 2400, height: 1200 } },
  summary: { value: '<p>Twenty-two new models from Japan, including the INNO64 R34 Z-Tune and the first POP RACE Rocket Bunny Supras in NZ.</p>' },
  collection: { value: collections['jdm-legends'] },
  system: { url: 'drop.html', handle: 'japan-drop-005' }
};

IMAGES['img/article-r34.svg'] = heroSvg();
export const articles = [
  {
    id: 1,
    title: 'Best Nissan Skyline R34 Models in 1:64',
    url: 'article.html',
    author: 'Scale Culture',
    tags: ['Collector guides'],
    published_at: ago(3),
    updated_at: ago(2),
    image: { src: 'img/article-r34.svg', alt: 'R34 line-up', width: 2400, height: 1200 },
    excerpt_or_content: 'INNO64, MINI GT, Tomica Limited Vintage or Ignition? We line up every R34 worth owning in 1:64 — from the Midnight Purple V-Spec to the Nismo Z-Tune.',
    content: `<p>The R34 is the most-modelled JDM car of all time, and in 1:64 there has never been more choice. Here's how the major makers compare on detail, wheels, packaging and value.</p>
<h2>INNO64 — the detail benchmark</h2><p>INNO64's R34 V-Spec in Midnight Purple III is the one collectors chase. Opening bonnet, separate mirrors, correct LMGT4 wheels and a lovely deep paint finish.</p>
<h2>MINI GT — the value pick</h2><p>Around half the price of INNO64, MINI GT nails proportions and ships with the best acrylic display case at this scale.</p>
<h2>Tomica Limited Vintage — the purist's choice</h2><p>TLV's R34s are understated and true to the factory spec, with the best tampo printing of the lot.</p>
<h2>Which should you buy?</h2><p>If you only buy one, start with the INNO64 V-Spec. If you're building a full R34 garage, MINI GT is the way to fill out the colours.</p>`,
    metafields: { scale: { products: { value: [by('inno64-r34-midnight-purple'), by('ignition-r34-z-tune'), by('tlv-skyline-kpgc10'), by('minigt-nsx-type-r-white')] } } }
  },
  {
    id: 2, title: 'MINI GT vs INNO64: Which 1:64 Brand Is Right for You?', url: 'article.html', author: 'Scale Culture', tags: ['Brand guides'], published_at: ago(10), updated_at: ago(10),
    image: { src: 'img/tile-minigt-nsx-type-r-white.svg', alt: '', width: 800, height: 800 }, excerpt_or_content: 'Price, detail, packaging and range — a side-by-side on the two biggest names in premium 1:64.', content: '', metafields: { scale: {} }
  },
  {
    id: 3, title: "Beginner's Guide to Building Aoshima Kits", url: 'article.html', author: 'Scale Culture', tags: ['Build guides'], published_at: ago(18), updated_at: ago(18),
    image: { src: 'img/tile-aoshima-fd3s-kit.svg', alt: '', width: 800, height: 800 }, excerpt_or_content: 'Glue, paint and patience: everything you need for your first 1:24 plastic kit.', content: '', metafields: { scale: {} }
  },
  {
    id: 4, title: 'Understanding Die-Cast Model Scales', url: 'article.html', author: 'Scale Culture', tags: ['Collector guides'], published_at: ago(25), updated_at: ago(25),
    image: { src: 'img/tile-ignition-r34-z-tune.svg', alt: '', width: 800, height: 800 }, excerpt_or_content: '1:64, 1:43, 1:24, 1:18 — what the numbers mean, how big each really is, and which to collect.', content: '', metafields: { scale: {} }
  }
];
export const blog = { title: 'Journal', url: 'journal.html', articles, articles_count: articles.length, all_tags: ['Collector guides', 'Brand guides', 'Build guides', 'New releases'] };

// A collector with a garage, for the My Garage preview
const entry = (h, status, colour) => {
  const p = by(h);
  const m = p.metafields.scale;
  return {
    pid: String(p.id), handle: h, title: p.title, card_title: m.card_title.value, vendor: p.vendor, image: p.media[0].src, scale: m.scale.value,
    make: m.vehicle_make.value, model: m.vehicle_model.value, gen: m.vehicle_generation?.value || '', colour: colour || m.colour.value,
    group: [m.vehicle_make.value, m.vehicle_model.value, m.vehicle_generation?.value].filter(Boolean).join(' '), status
  };
};
const garage = [
  entry('inno64-r34-midnight-purple', 'owned'),
  entry('ignition-r34-z-tune', 'owned', 'Nismo Z-Tune'),
  { ...entry('inno64-r34-midnight-purple', 'owned', 'Bayside Blue'), pid: '9001' },
  { ...entry('inno64-r34-midnight-purple', 'wanted', "Mine's R34"), pid: '9002' },
  { ...entry('inno64-r34-midnight-purple', 'wanted', 'V-Spec II Nür'), pid: '9003' },
  entry('poprace-a80-rocket-bunny', 'preordered'),
  entry('inno64-fd3s-re-amemiya', 'owned'),
  entry('tarmac-911-gt3r-hong-kong', 'owned'),
  entry('minigt-nsx-type-r-white', 'wanted')
];
export const customer = {
  id: 42,
  email: 'collector@example.co.nz',
  first_name: 'Sam',
  metafields: {
    scale: {
      garage: { value: garage },
      garage_stats: {
        value: {
          owned: 84, wanted: 3, preordered: 1,
          makes: [{ make: 'Nissan', count: 21 }, { make: 'Porsche', count: 17 }, { make: 'Toyota', count: 12 }, { make: 'BMW', count: 8 }, { make: 'Other', count: 26 }],
          collections: [{ group: 'Nissan Skyline R34', count: 5 }],
          top_make_handles: ['nissan', 'mazda', 'toyota'],
          top_scale: '1:64'
        }
      },
      profile: { value: { display_name: 'R34 Hunter', public: true, slug: 'r34-hunter', interests: { makes: ['Nissan', 'Mazda'], scales: ['1:64'], brands: ['INNO64'], categories: ['JDM'] } } },
      wishlist: { value: [] }
    }
  }
};
