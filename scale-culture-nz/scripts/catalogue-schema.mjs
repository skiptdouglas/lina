// Single source of truth for the Scale Culture NZ product data model (SOP §9–§12, §15, §17).
// Used by setup-store.mjs (creates definitions in Shopify) and validate-catalogue.mjs (checks CSVs).

export const NAMESPACE = 'scale';

export const SCALES = ['1:64', '1:43', '1:24', '1:18', '1:12', '1:32', '1:87', 'Other'];

export const PRODUCT_TYPES = ['Die-cast', 'Plastic Model Kit', 'Accessory'];

export const VEHICLE_MAKES = [
  'Nissan', 'Toyota', 'Honda', 'Mazda', 'Mitsubishi', 'Subaru', 'Porsche', 'BMW', 'Mercedes-Benz',
  'Ford', 'Chevrolet', 'Ferrari', 'Lamborghini', 'McLaren', 'Audi', 'Volkswagen',
  // Beyond the SOP's initial list — common in the target catalogue
  'Lexus', 'Suzuki', 'Daihatsu', 'Isuzu', 'Datsun', 'Acura', 'Infiniti', 'Alfa Romeo', 'Lancia',
  'Aston Martin', 'Bugatti', 'Pagani', 'Koenigsegg', 'Dodge', 'Jaguar', 'Lotus', 'Mini', 'Renault',
  'Peugeot', 'Holden', 'Other'
];

export const MOTORSPORT = [
  'Super GT', 'JGTC', 'Group A', 'Group B', 'Group C', 'WRC', 'Le Mans', 'Touring Cars', 'Formula',
  'Drift', 'Time Attack', 'Drag', 'Rally', 'Endurance', 'None'
];

export const AVAILABILITY = ['auto', 'coming_soon', 'incoming', 'preorder', 'discontinued'];

// Vehicle model hierarchy (SOP §10) — the validator warns on unknown models so
// spellings stay consistent for filters ("Skyline", never "skyline gtr").
export const VEHICLE_MODELS = {
  Nissan: { Skyline: ['R32', 'R33', 'R34', 'KPGC10', 'KPGC110', 'R31', 'V35'], 'GT-R': ['R35'], 'Silvia': ['S13', 'S14', 'S15'], 'Fairlady Z': ['S30', 'Z32', 'Z33', 'Z34', 'RZ34'], '180SX': [], 'Stagea': [] },
  Toyota: { Supra: ['A70', 'A80', 'A90'], AE86: ['Trueno', 'Levin'], GR86: [], Celica: ['ST165', 'ST185', 'ST205'], 'GR Yaris': [], Chaser: ['JZX100'], 'Land Cruiser': [], '2000GT': [] },
  Mazda: { 'RX-7': ['FC3S', 'FD3S', 'SA22C'], 'MX-5': ['NA', 'NB', 'NC', 'ND'], 'RX-8': [], '787B': [] },
  Honda: { Civic: ['EG6', 'EK9', 'FD2', 'FK8', 'FL5'], NSX: ['NA1', 'NA2', 'NC1'], Integra: ['DC2', 'DC5'], S2000: ['AP1', 'AP2'], 'S800': [] },
  Mitsubishi: { 'Lancer Evolution': ['III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'], 'Pajero': [], 'GTO': [] },
  Subaru: { 'Impreza WRX': ['GC8', 'GDB', 'GRB'], 'BRZ': [], '22B': [] },
  Porsche: { '911': ['930', '964', '993', '996', '997', '991', '992'], '356': [], '917': [], '962': [], 'Cayman': [] }
};

/**
 * Product metafield definitions. `filter: true` marks the ones to enable in
 * Search & Discovery (storefront filters) and smart-collection conditions.
 */
export const PRODUCT_METAFIELDS = [
  { key: 'scale', name: 'Scale', type: 'single_line_text_field', choices: SCALES, required: true, filter: true },
  { key: 'vehicle_make', name: 'Vehicle manufacturer', type: 'single_line_text_field', choices: VEHICLE_MAKES, required: true, filter: true },
  { key: 'vehicle_model', name: 'Vehicle model', type: 'single_line_text_field', required: true, filter: true, description: 'e.g. Skyline, Supra, RX-7, 911' },
  { key: 'vehicle_generation', name: 'Vehicle generation', type: 'single_line_text_field', filter: true, description: 'Chassis code e.g. R34, A80, FD3S, 964' },
  { key: 'availability', name: 'Availability override', type: 'single_line_text_field', choices: AVAILABILITY, required: true, filter: true, description: 'auto = derive from inventory. Use coming_soon → incoming → auto through the inventory workflow; preorder for pre-orders.' },
  { key: 'card_title', name: 'Card title', type: 'single_line_text_field', description: 'Short vehicle name for product cards, e.g. "Nissan Skyline GT-R R34"' },
  { key: 'colour', name: 'Colour', type: 'single_line_text_field' },
  { key: 'vehicle_year', name: 'Vehicle year', type: 'number_integer' },
  { key: 'series', name: 'Series', type: 'single_line_text_field' },
  { key: 'motorsport_category', name: 'Motorsport category', type: 'single_line_text_field', choices: MOTORSPORT, filter: true },
  { key: 'street_race', name: 'Street / Race', type: 'single_line_text_field', choices: ['Street', 'Race'], filter: true },
  { key: 'release_date', name: 'Release date', type: 'date' },
  { key: 'country_of_origin', name: 'Country of origin', type: 'single_line_text_field', filter: true, description: 'Country of the vehicle manufacturer, e.g. Japan, Germany' },
  { key: 'limited_edition', name: 'Limited edition', type: 'boolean', filter: true },
  { key: 'limited_edition_note', name: 'Limited edition note', type: 'single_line_text_field', description: 'e.g. "1 of 3,600"' },
  { key: 'mpn', name: 'Manufacturer model number', type: 'single_line_text_field' },
  { key: 'package_dimensions', name: 'Package dimensions', type: 'single_line_text_field' },
  { key: 'preorder_jp_release', name: 'Pre-order: expected Japanese release', type: 'single_line_text_field', description: 'e.g. November 2026' },
  { key: 'preorder_nz_arrival', name: 'Pre-order: expected NZ arrival', type: 'single_line_text_field', description: 'e.g. December 2026' },
  { key: 'preorder_deposit', name: 'Pre-order: deposit', type: 'single_line_text_field', description: 'e.g. $10 — leave blank if paid in full' },
  { key: 'preorder_allocation', name: 'Pre-order: total allocation', type: 'number_integer' },
  { key: 'drop', name: 'Drop', type: 'metaobject_reference', metaobject: 'drop' }
];

export const COLLECTION_METAFIELDS = [
  { key: 'brand_logo', name: 'Brand logo', type: 'file_reference', fileTypes: ['Image'] }
];

export const DROP_METAOBJECT = {
  type: 'drop',
  name: 'Drop',
  displayNameKey: 'name',
  urlHandle: 'drop',
  fields: [
    { key: 'name', name: 'Drop name', type: 'single_line_text_field', required: true },
    { key: 'number', name: 'Drop number', type: 'number_integer', required: true },
    { key: 'release_date', name: 'Release date', type: 'date_time', required: true },
    { key: 'brands', name: 'Brands included', type: 'list.single_line_text_field' },
    { key: 'image', name: 'Promotional image', type: 'file_reference' },
    { key: 'summary', name: 'Summary', type: 'rich_text_field' },
    { key: 'collection', name: 'Product collection', type: 'collection_reference', required: true }
  ]
};

export const BRANDS = [
  'MINI GT', 'Kaido House', 'INNO64', 'Tarmac Works', 'POP RACE', 'Hobby Japan',
  'Tomica Limited Vintage', 'Kyosho', 'Ignition Model', 'Aoshima', 'Fujimi', 'Hasegawa', 'Tamiya'
];

export const EDITORIAL_COLLECTIONS = [
  'JDM Legends', '90s Japan', 'Group A', 'Super GT', 'WRC', 'Le Mans', 'Touring Cars',
  'Liberty Walk', 'RWB', 'Rocket Bunny', 'Porsche Icons', 'Skyline GT-R'
];

export const KIT_CATEGORIES = [
  'Japanese Cars', 'European Cars', 'American Cars', 'Race Cars', 'Motorcycles', 'Classic Cars', 'Tuner Cars'
];

export const ACCESSORY_CATEGORIES = [
  'Display cases', 'Dioramas', 'Wheels', 'Tyres', 'Decals', 'Detailing parts', 'Paint', 'Tools', 'Lighting', 'Display stands'
];

export const handleize = (s) =>
  s.toLowerCase().replace(/:/g, '-').replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
