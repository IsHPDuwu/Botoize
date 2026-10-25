/**
 * Category, group, and entry model for the system settings page.
 *
 * Order and ids are part of the UI contract defined in
 * `spec/system-settings-ui.spec.md` (SSU-1, SSU-1a, SSU-1b). Entries are the single
 * source of every row label and description, so search always matches what the
 * page renders.
 */
export const SETTINGS_CATEGORIES = [
  {
    id: "site",
    titleKey: "settings.siteInformation",
    descriptionKey: "settings.siteInfoDescription",
  },
  {
    id: "access",
    titleKey: "settings.accessControl",
    descriptionKey: "settings.accessControlDescription",
  },
  {
    id: "codex",
    titleKey: "settings.codexModels",
    descriptionKey: "settings.codexModelsDescription",
  },
  {
    id: "suffix",
    titleKey: "settings.reasoningSuffixMap",
    descriptionKey: "settings.reasoningSuffixMapDescription",
  },
  {
    id: "redirects",
    titleKey: "settings.globalModelRedirects",
    descriptionKey: "settings.globalModelRedirectsDescription",
  },
  {
    id: "transforms",
    titleKey: "settings.globalTransforms",
    descriptionKey: "settings.globalTransformsDescription",
  },
  {
    id: "affinity",
    titleKey: "settings.affinityRouting",
    descriptionKey: "settings.affinityRoutingDescription",
  },
  {
    id: "health",
    titleKey: "settings.healthMonitoring",
    descriptionKey: "settings.healthMonitoringDescription",
  },
  {
    id: "extra",
    titleKey: "settings.extraFieldsWhitelist",
    descriptionKey: "settings.extraFieldsWhitelistDescription",
  },
] as const;

export type SettingsCategory = (typeof SETTINGS_CATEGORIES)[number];
export type SettingsCategoryId = SettingsCategory["id"];

/**
 * A row group renders its entries as rows on one `Card`; an editor group (`editor`)
 * renders one self-framed editor without a `Card` (SSU-1a).
 */
export interface SettingsGroup {
  category: SettingsCategoryId;
  titleKey?: string;
  editor?: true;
}

export const SETTINGS_GROUPS = {
  site: { category: "site" },
  "access.registration": { category: "access", titleKey: "settings.registration" },
  "access.session": { category: "access", titleKey: "settings.sessionSecurity" },
  codex: { category: "codex", editor: true },
  suffix: { category: "suffix", editor: true },
  redirects: { category: "redirects", editor: true },
  transforms: { category: "transforms", editor: true },
  affinity: { category: "affinity" },
  "health.probe": { category: "health", titleKey: "settings.groupActiveProbe" },
  "health.passive": { category: "health", titleKey: "settings.groupPassiveBreaker" },
  "health.capture": { category: "health", titleKey: "settings.groupRequestCapture" },
  "health.runtime": { category: "health", titleKey: "settings.groupRuntimeBehavior" },
  "health.dashboard": {
    category: "health",
    titleKey: "settings.dashboardPerformanceTitle",
    editor: true,
  },
  extra: { category: "extra" },
} as const satisfies Record<string, SettingsGroup>;

export type SettingsGroupId = keyof typeof SETTINGS_GROUPS;

export interface SettingEntry {
  /** Row DOM id suffix; also the control id for single-control rows. */
  id: string;
  group: SettingsGroupId;
  /** i18n key of the visible label. */
  labelKey?: string;
  /** Untranslated label, rendered in the mono face (protocol type ids). */
  rawLabel?: string;
  descriptionKey?: string;
  /**
   * Extra searchable text keys: editor help text, and for editor entries the category
   * description, which is the only prose describing the editor.
   */
  helpKeys?: readonly string[];
  /** API field names, matched verbatim by search. */
  fields: readonly string[];
}

function extraFieldsEntry<K extends string>(subKey: K) {
  return {
    id: `extra_fields_${subKey}` as const,
    group: "extra",
    rawLabel: subKey,
    helpKeys: ["settings.extraFieldsWhitelistHelp"],
    fields: ["botoize_extra_fields_whitelist", subKey],
  } as const;
}

export const SETTING_ENTRIES = [
  { id: "site_name", group: "site", labelKey: "settings.siteName", fields: ["site_name"] },
  {
    id: "site_description",
    group: "site",
    labelKey: "settings.siteDescription",
    fields: ["site_description"],
  },
  {
    id: "api_base_url",
    group: "site",
    labelKey: "settings.apiBaseUrl",
    descriptionKey: "settings.apiBaseUrlDescription",
    fields: ["api_base_url"],
  },
  {
    id: "recharge_public_origin",
    group: "site",
    labelKey: "settings.rechargePublicOrigin",
    descriptionKey: "settings.rechargePublicOriginDescription",
    fields: ["recharge_public_origin"],
  },
  {
    id: "registration_enabled",
    group: "access.registration",
    labelKey: "settings.allowRegistration",
    descriptionKey: "settings.allowRegistrationDescription",
    fields: ["registration_enabled"],
  },
  {
    id: "default_user_role",
    group: "access.registration",
    labelKey: "settings.defaultUserRole",
    descriptionKey: "settings.defaultUserRoleDescription",
    fields: ["default_user_role"],
  },
  {
    id: "captcha_enabled",
    group: "access.session",
    labelKey: "settings.captchaEnabled",
    descriptionKey: "settings.captchaEnabledDescription",
    fields: ["captcha_enabled"],
  },
  {
    id: "session_ttl_days",
    group: "access.session",
    labelKey: "settings.sessionDuration",
    descriptionKey: "settings.sessionDurationDescription",
    fields: ["session_ttl_days"],
  },
  {
    id: "api_key_max_per_user",
    group: "access.session",
    labelKey: "settings.maxApiKeys",
    descriptionKey: "settings.maxApiKeysDescription",
    fields: ["api_key_max_per_user"],
  },
  {
    id: "codex_model_ids",
    group: "codex",
    helpKeys: ["settings.codexModelsDescription", "settings.codexModelsCompatibilityHelp"],
    fields: ["codex_model_ids"],
  },
  {
    id: "reasoning_suffix_map",
    group: "suffix",
    helpKeys: ["settings.reasoningSuffixMapDescription", "settings.effortValues"],
    fields: ["reasoning_suffix_map"],
  },
  {
    id: "global_model_redirects",
    group: "redirects",
    helpKeys: ["settings.globalModelRedirectsDescription", "settings.globalModelRedirectsHelp"],
    fields: ["global_model_redirects"],
  },
  {
    id: "global_transforms",
    group: "transforms",
    helpKeys: ["settings.globalTransformsDescription", "settings.globalTransformsHelp"],
    fields: ["global_transforms"],
  },
  {
    id: "botoize_affinity_enabled",
    group: "affinity",
    labelKey: "settings.affinityEnabled",
    descriptionKey: "settings.affinityEnabledDescription",
    fields: ["botoize_affinity_enabled"],
  },
  {
    id: "botoize_affinity_failback_mode",
    group: "affinity",
    labelKey: "settings.affinityFailbackMode",
    descriptionKey: "settings.affinityFailbackModeDescription",
    fields: ["botoize_affinity_failback_mode"],
  },
  {
    id: "botoize_affinity_idle_ttl_seconds",
    group: "affinity",
    labelKey: "settings.affinityIdleTtlSeconds",
    descriptionKey: "settings.affinityIdleTtlSecondsDescription",
    fields: ["botoize_affinity_idle_ttl_seconds"],
  },
  {
    id: "botoize_affinity_failback_delay_seconds",
    group: "affinity",
    labelKey: "settings.affinityFailbackDelaySeconds",
    descriptionKey: "settings.affinityFailbackDelaySecondsDescription",
    fields: ["botoize_affinity_failback_delay_seconds"],
  },
  {
    id: "botoize_active_probe_enabled",
    group: "health.probe",
    labelKey: "settings.activeProbeEnabled",
    descriptionKey: "settings.activeProbeEnabledDescription",
    fields: ["botoize_active_probe_enabled"],
  },
  {
    id: "botoize_active_probe_interval_seconds",
    group: "health.probe",
    labelKey: "settings.activeProbeIntervalSeconds",
    descriptionKey: "settings.activeProbeIntervalSecondsDescription",
    fields: ["botoize_active_probe_interval_seconds"],
  },
  {
    id: "botoize_active_probe_success_threshold",
    group: "health.probe",
    labelKey: "settings.activeProbeSuccessThreshold",
    descriptionKey: "settings.activeProbeSuccessThresholdDescription",
    fields: ["botoize_active_probe_success_threshold"],
  },
  {
    id: "botoize_active_probe_model",
    group: "health.probe",
    labelKey: "settings.activeProbeModel",
    descriptionKey: "settings.activeProbeModelDescription",
    fields: ["botoize_active_probe_model"],
  },
  {
    id: "botoize_passive_failure_threshold",
    group: "health.passive",
    labelKey: "settings.passiveFailureThreshold",
    descriptionKey: "settings.passiveFailureThresholdDescription",
    fields: ["botoize_passive_failure_threshold"],
  },
  {
    id: "botoize_passive_cooldown_seconds",
    group: "health.passive",
    labelKey: "settings.passiveCooldownSeconds",
    descriptionKey: "settings.passiveCooldownSecondsDescription",
    fields: ["botoize_passive_cooldown_seconds"],
  },
  {
    id: "botoize_passive_window_seconds",
    group: "health.passive",
    labelKey: "settings.passiveWindowSeconds",
    descriptionKey: "settings.passiveWindowSecondsDescription",
    fields: ["botoize_passive_window_seconds"],
  },
  {
    id: "botoize_passive_min_samples",
    group: "health.passive",
    labelKey: "settings.passiveMinSamples",
    descriptionKey: "settings.passiveMinSamplesDescription",
    fields: ["botoize_passive_min_samples"],
  },
  {
    id: "botoize_passive_failure_rate_threshold",
    group: "health.passive",
    labelKey: "settings.passiveFailureRateThreshold",
    descriptionKey: "settings.passiveFailureRateThresholdDescription",
    fields: ["botoize_passive_failure_rate_threshold"],
  },
  {
    id: "botoize_passive_rate_limit_cooldown_seconds",
    group: "health.passive",
    labelKey: "settings.passiveRateLimitCooldownSeconds",
    descriptionKey: "settings.passiveRateLimitCooldownSecondsDescription",
    fields: ["botoize_passive_rate_limit_cooldown_seconds"],
  },
  {
    id: "botoize_request_capture_enabled",
    group: "health.capture",
    labelKey: "settings.requestCaptureEnabled",
    descriptionKey: "settings.requestCaptureEnabledDescription",
    fields: ["botoize_request_capture_enabled"],
  },
  {
    id: "botoize_mask_sensitive_info",
    group: "health.capture",
    labelKey: "settings.maskSensitiveInfo",
    descriptionKey: "settings.maskSensitiveInfoDescription",
    fields: ["botoize_mask_sensitive_info"],
  },
  {
    id: "botoize_request_capture_max_total_bytes",
    group: "health.capture",
    labelKey: "settings.requestCaptureMaxTotalMib",
    descriptionKey: "settings.requestCaptureMaxTotalMibDescription",
    fields: ["botoize_request_capture_max_total_bytes"],
  },
  {
    id: "botoize_enable_estimated_billing",
    group: "health.runtime",
    labelKey: "settings.enableEstimatedBilling",
    descriptionKey: "settings.enableEstimatedBillingDescription",
    fields: ["botoize_enable_estimated_billing"],
  },
  {
    id: "botoize_strip_cross_protocol_nested_extra",
    group: "health.runtime",
    labelKey: "settings.stripCrossProtocolNestedExtra",
    descriptionKey: "settings.stripCrossProtocolNestedExtraDescription",
    fields: ["botoize_strip_cross_protocol_nested_extra"],
  },
  {
    id: "allow_free_when_unpriced",
    group: "health.runtime",
    labelKey: "settings.allowFreeWhenUnpriced",
    descriptionKey: "settings.allowFreeWhenUnpricedDescription",
    fields: ["allow_free_when_unpriced"],
  },
  {
    id: "allow_free_when_missing_usage",
    group: "health.runtime",
    labelKey: "settings.allowFreeWhenMissingUsage",
    descriptionKey: "settings.allowFreeWhenMissingUsageDescription",
    fields: ["allow_free_when_missing_usage"],
  },
  {
    id: "botoize_request_timeout_ms",
    group: "health.runtime",
    labelKey: "settings.requestTimeoutMs",
    descriptionKey: "settings.requestTimeoutMsDescription",
    fields: ["botoize_request_timeout_ms"],
  },
  {
    id: "dashboard_performance_targets",
    group: "health.dashboard",
    helpKeys: [
      "settings.dashboardPerformanceDescription",
      "settings.dashboardPerformanceGroups",
      "settings.dashboardPerformanceModels",
    ],
    fields: ["dashboard_performance_group_ids", "dashboard_performance_model_ids"],
  },
  extraFieldsEntry("chat_completion"),
  extraFieldsEntry("responses"),
  extraFieldsEntry("messages"),
  extraFieldsEntry("gemini"),
] as const satisfies readonly SettingEntry[];

export type SettingEntryId = (typeof SETTING_ENTRIES)[number]["id"];

const ENTRY_BY_ID = new Map<string, SettingEntry>(
  SETTING_ENTRIES.map((entry) => [entry.id, entry])
);

export function getSettingEntry(id: SettingEntryId): SettingEntry {
  return ENTRY_BY_ID.get(id)!;
}

export function categoryOfGroup(group: SettingsGroupId): SettingsCategoryId {
  return SETTINGS_GROUPS[group].category;
}
