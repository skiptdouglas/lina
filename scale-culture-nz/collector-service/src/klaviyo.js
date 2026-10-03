// Pushes collector interests and garage/wishlist summaries to the customer's Klaviyo
// profile so campaigns and flows can target them (SOP §21, §37 interest-based notifications).

const REVISION = '2024-10-15';

export function klaviyoProperties({ profile, stats, wishlist }) {
  return {
    sc_collector_name: profile?.display_name || null,
    sc_interest_makes: profile?.interests?.makes || [],
    sc_interest_scales: profile?.interests?.scales || [],
    sc_interest_brands: profile?.interests?.brands || [],
    sc_interest_categories: profile?.interests?.categories || [],
    sc_garage_owned: stats?.owned ?? 0,
    sc_garage_wanted: stats?.wanted ?? 0,
    sc_garage_top_makes: (stats?.makes || []).filter((m) => m.make !== 'Other').map((m) => m.make),
    sc_garage_top_scale: stats?.top_scale || null,
    sc_wishlist: wishlist || []
  };
}

export function createKlaviyo({ apiKey, fetchImpl = fetch, log = console }) {
  return {
    enabled: Boolean(apiKey),
    async updateProfile(email, properties) {
      if (!apiKey || !email) return false;
      try {
        const res = await fetchImpl('https://a.klaviyo.com/api/profile-import', {
          method: 'POST',
          headers: {
            Authorization: `Klaviyo-API-Key ${apiKey}`,
            revision: REVISION,
            'Content-Type': 'application/vnd.api+json',
            Accept: 'application/vnd.api+json'
          },
          body: JSON.stringify({ data: { type: 'profile', attributes: { email, properties } } })
        });
        if (!res.ok) log.warn(`klaviyo profile-import ${res.status}`);
        return res.ok;
      } catch (e) {
        // Best effort: never fail a garage/profile save because Klaviyo is down
        log.warn(`klaviyo profile-import failed: ${e.message}`);
        return false;
      }
    }
  };
}
