export const POLICY_SCOPES = Object.freeze({
  group: Object.freeze({
    idKey: "group_id",
    listKey: "group_policies",
    recordKey: "group_policy",
    listEndpoint: "content-safety/group-policies",
    saveEndpoint: "content-safety/group-policy",
    removeEndpoint: "content-safety/group-policy/remove",
    objectLabel: "群",
    idLabel: "群 ID",
  }),
  private: Object.freeze({
    idKey: "user_id",
    listKey: "private_policies",
    recordKey: "private_policy",
    listEndpoint: "content-safety/private-policies",
    saveEndpoint: "content-safety/private-policy",
    removeEndpoint: "content-safety/private-policy/remove",
    objectLabel: "用户",
    idLabel: "用户 ID",
  }),
});

const copyRecord = (record) => (record ? { ...record } : null);

export function createPolicyBucket(scope = "group") {
  if (!POLICY_SCOPES[scope]) throw new Error(`Unknown policy scope: ${scope}`);
  return {
    scope,
    records: [],
    selectedId: "",
    draft: null,
    baseline: null,
    search: "",
    loading: false,
    saving: false,
    deleting: false,
    loaded: false,
    error: "",
  };
}

export function policyRecordId(scope, record) {
  const definition = POLICY_SCOPES[scope];
  if (!definition) return "";
  return String(record?.[definition.idKey] ?? "").trim();
}

function comparable(scope, record) {
  if (!record) return null;
  return {
    id: policyRecordId(scope, record),
    generalOnly: record.general_only_enabled === true,
    builtinTerms: record.builtin_terms_enabled === true,
  };
}

export function hasUnsavedPolicyDraft(bucket) {
  return JSON.stringify(comparable(bucket.scope, bucket.draft)) !==
    JSON.stringify(comparable(bucket.scope, bucket.baseline));
}

export function selectPolicyRecord(bucket, scope, id) {
  const normalizedId = String(id ?? "").trim();
  const record = bucket.records.find(
    (candidate) => policyRecordId(scope, candidate) === normalizedId,
  );
  return {
    ...bucket,
    scope,
    selectedId: record ? normalizedId : "",
    draft: copyRecord(record),
    baseline: copyRecord(record),
    error: "",
  };
}

export function replacePolicyRecords(bucket, scope, records, preferredId = bucket.selectedId) {
  const normalized = Array.isArray(records)
    ? records.filter((record) => policyRecordId(scope, record))
    : [];
  const requested = String(preferredId ?? "").trim();
  const selectedId = normalized.some(
    (record) => policyRecordId(scope, record) === requested,
  ) ? requested : policyRecordId(scope, normalized[0]);
  return selectPolicyRecord(
    { ...bucket, scope, records: normalized.map(copyRecord), loaded: true, error: "" },
    scope,
    selectedId,
  );
}

export function upsertPolicyRecord(bucket, scope, record) {
  const id = policyRecordId(scope, record);
  if (!id) return bucket;
  const records = bucket.records.filter(
    (candidate) => policyRecordId(scope, candidate) !== id,
  );
  records.push(copyRecord(record));
  records.sort((left, right) =>
    policyRecordId(scope, left).localeCompare(policyRecordId(scope, right)),
  );
  return selectPolicyRecord({ ...bucket, records }, scope, id);
}

export function removePolicyRecord(bucket, scope, id) {
  const normalizedId = String(id ?? "").trim();
  const oldIndex = bucket.records.findIndex(
    (record) => policyRecordId(scope, record) === normalizedId,
  );
  const records = bucket.records.filter(
    (record) => policyRecordId(scope, record) !== normalizedId,
  );
  const adjacent = records[Math.min(Math.max(oldIndex, 0), records.length - 1)];
  return selectPolicyRecord(
    { ...bucket, records },
    scope,
    policyRecordId(scope, adjacent),
  );
}

export function discardPolicyDraft(bucket) {
  return { ...bucket, draft: copyRecord(bucket.baseline), error: "" };
}
