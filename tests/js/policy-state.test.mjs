import test from "node:test";
import assert from "node:assert/strict";
import {
  POLICY_SCOPES,
  createPolicyBucket,
  policyRecordId,
  hasUnsavedPolicyDraft,
  selectPolicyRecord,
  replacePolicyRecords,
  upsertPolicyRecord,
  removePolicyRecord,
  discardPolicyDraft,
} from "../../pages/pluginCenter/policy-state.mjs";

const group = (id, general = true, builtin = true) => ({
  group_id: id,
  general_only_enabled: general,
  builtin_terms_enabled: builtin,
});
const user = (id, general = true, builtin = true) => ({
  user_id: id,
  general_only_enabled: general,
  builtin_terms_enabled: builtin,
});

test("scope definitions map independent fields and endpoints", () => {
  assert.equal(POLICY_SCOPES.group.idKey, "group_id");
  assert.equal(POLICY_SCOPES.private.idKey, "user_id");
  assert.match(POLICY_SCOPES.private.listEndpoint, /private-policies$/);
  assert.match(POLICY_SCOPES.group.removeEndpoint, /group-policy\/remove$/);
});

test("policyRecordId normalizes the active scope identifier", () => {
  assert.equal(policyRecordId("group", group(" 100 ")), "100");
  assert.equal(policyRecordId("private", user(" u1 ")), "u1");
  assert.equal(policyRecordId("private", group("100")), "");
});

test("group and private buckets remain isolated with the same ID", () => {
  const groups = upsertPolicyRecord(createPolicyBucket("group"), "group", group("1", false));
  const users = upsertPolicyRecord(createPolicyBucket("private"), "private", user("1", true, false));
  assert.equal(groups.records[0].general_only_enabled, false);
  assert.equal(users.records[0].builtin_terms_enabled, false);
  assert.equal(groups.records[0].user_id, undefined);
});

test("replace preserves a valid selection and falls back to the first record", () => {
  const bucket = replacePolicyRecords(createPolicyBucket("group"), "group", [group("1"), group("2")], "2");
  assert.equal(bucket.selectedId, "2");
  const replaced = replacePolicyRecords(bucket, "group", [group("3"), group("4")]);
  assert.equal(replaced.selectedId, "3");
});

test("select creates independent baseline and draft copies", () => {
  let bucket = replacePolicyRecords(createPolicyBucket("private"), "private", [user("u1")]);
  bucket = selectPolicyRecord(bucket, "private", "u1");
  bucket.draft.general_only_enabled = false;
  assert.equal(bucket.baseline.general_only_enabled, true);
  assert.equal(hasUnsavedPolicyDraft(bucket), true);
});

test("upsert replaces without duplication and marks the saved record clean", () => {
  let bucket = replacePolicyRecords(createPolicyBucket("group"), "group", [group("1")]);
  bucket = upsertPolicyRecord(bucket, "group", group("1", false, false));
  assert.equal(bucket.records.length, 1);
  assert.equal(bucket.draft.general_only_enabled, false);
  assert.equal(hasUnsavedPolicyDraft(bucket), false);
});

test("discard restores the saved baseline", () => {
  let bucket = replacePolicyRecords(createPolicyBucket("private"), "private", [user("u1")]);
  bucket.draft.builtin_terms_enabled = false;
  bucket = discardPolicyDraft(bucket);
  assert.equal(bucket.draft.builtin_terms_enabled, true);
  assert.equal(hasUnsavedPolicyDraft(bucket), false);
});

test("remove selects the adjacent record", () => {
  let bucket = replacePolicyRecords(createPolicyBucket("group"), "group", [group("1"), group("2"), group("3")], "2");
  bucket = removePolicyRecord(bucket, "group", "2");
  assert.deepEqual(bucket.records.map((record) => record.group_id), ["1", "3"]);
  assert.equal(bucket.selectedId, "3");
});

test("removing the final record clears selection and draft", () => {
  let bucket = replacePolicyRecords(createPolicyBucket("private"), "private", [user("u1")]);
  bucket = removePolicyRecord(bucket, "private", "u1");
  assert.equal(bucket.selectedId, "");
  assert.equal(bucket.draft, null);
  assert.equal(bucket.records.length, 0);
});

test("request state and search are local to each bucket", () => {
  const groups = { ...createPolicyBucket("group"), loading: true, search: "10" };
  const users = createPolicyBucket("private");
  assert.equal(groups.loading, true);
  assert.equal(groups.search, "10");
  assert.equal(users.loading, false);
  assert.equal(users.search, "");
});
