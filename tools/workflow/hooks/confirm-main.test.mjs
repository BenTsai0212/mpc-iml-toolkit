import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { decide, evaluate, MERGE_DENY_NOTE, REMOTE_DENY_NOTE } from './confirm-main.mjs';

const onMain = { currentBranch: () => 'main' };
const onFeature = { currentBranch: () => 'feat/1-x' };

const asks = (command, ctx = onFeature) =>
  assert.ok(evaluate(command, ctx), `應攔截：${command}`);
const passes = (command, ctx = onFeature) =>
  assert.equal(evaluate(command, ctx), null, `不應攔截：${command}`);

test('gh pr merge：任何參數都攔', () => {
  asks('gh pr merge');
  asks('gh pr merge 12 --squash --delete-branch');
  asks('gh pr merge --auto -R owner/repo 3');
});

test('gh pr merge：其他 gh 指令不攔', () => {
  passes('gh pr view 12');
  passes('gh pr create --title "merge 說明"');
  passes('gh issue list --search "gh pr merge"');
});

test('git push：明寫 main 的各種形式都攔', () => {
  asks('git push origin main');
  asks('git push origin HEAD:main');
  asks('git push origin feat/1-x:main');
  asks('git push origin refs/heads/main');
  asks('git push origin HEAD:refs/heads/main');
  asks('git push -u origin main');
  asks('git -C /tmp/repo push origin main');
});

test('git push：目標不是 main 不攔', () => {
  passes('git push origin feat/1-x');
  passes('git push -u origin HEAD');
  passes('git push origin main:feat/1-x');
  passes('git push origin maintenance');
  passes('git push origin refs/heads/main-old');
});

test('git push：未指定 refspec 時依目前分支判斷', () => {
  asks('git push', onMain);
  asks('git push origin', onMain);
  asks('git push -u origin HEAD', onMain);
  passes('git push');
  passes('git push origin');
});

test('git push：對 main 強制推送都攔', () => {
  asks('git push --force origin main');
  asks('git push -f origin main');
  asks('git push --force-with-lease origin main');
  asks('git push --force-with-lease=main:abc123 origin main');
  asks('git push origin +main');
  asks('git push origin +HEAD:main');
  asks('git push -f', onMain);
});

test('git push：強制推送到其他分支不攔', () => {
  passes('git push --force origin feat/1-x');
  passes('git push --force-with-lease origin HEAD');
  passes('git push origin +feat/1-x');
});

test('複合指令：任一段符合就攔', () => {
  asks('npm test && git push origin main');
  asks('npm test || gh pr merge 3');
  asks('echo ok; git push origin HEAD:main');
  asks('git log | head -1 | gh pr merge 3');
  asks('git status\ngit push origin main');
});

test('複合指令：每段都不符合就不攔', () => {
  passes('npm test && git push origin feat/1-x');
  passes('git status; git log --oneline | head -5');
});

test('引號內的文字不視為指令', () => {
  passes('git commit -m "之後再 git push origin main"');
  passes("echo 'gh pr merge 3 && git push origin main'");
});

test('目前分支無法判斷時，未指定 refspec 不攔', () => {
  passes('git push', { currentBranch: () => null });
});

test('子 shell 與 { } 群組：內部指令照樣判斷', () => {
  asks('(git push origin main)');
  asks('{ git push origin main; }');
  asks('npm test && (cd . && gh pr merge 3)');
  asks('if true; then git push origin main; fi');
  passes('(git push origin feat/1-x)');
  passes('{ git push origin feat/1-x; }');
});

test('絕對路徑的 git／gh 都攔', () => {
  asks('/usr/bin/git push origin main');
  asks('/opt/homebrew/bin/gh pr merge 7');
  passes('/usr/bin/git push origin feat/1-x');
  passes('/opt/homebrew/bin/gh pr view 7');
});

test('包裝指令（sudo、env、bash -c、sh -c）：內部指令照樣判斷', () => {
  asks('sudo git push origin main');
  asks('sudo -u root git push origin main');
  asks('env X=1 git push origin main');
  asks('env -u HOME X=1 /usr/bin/git push origin main');
  asks('nohup git push origin main');
  asks('bash -c "git push origin main"');
  asks("sh -c 'npm test && gh pr merge 3'");
  asks('bash -lc "git push origin HEAD:main"');
  asks('zsh -o pipefail -c "git push origin main"');
  asks("eval 'git push origin main'");
  passes('sudo git push origin feat/1-x');
  passes('env X=1 git push origin feat/1-x');
  passes('bash -c "git push origin feat/1-x"');
  passes("sh -c 'git status'");
  passes('bash script.sh main');
});

test('gh api 合併 PR 都攔', () => {
  asks('gh api -X PUT repos/o/r/pulls/7/merge');
  asks('gh api --method PUT repos/o/r/pulls/7/merge -f merge_method=squash');
  asks('gh api --method=put /repos/o/r/pulls/7/merge');
  asks('gh api -XPUT repos/{owner}/{repo}/pulls/7/merge');
  asks("gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'");
  passes('gh api repos/o/r/pulls/7/merge');
  passes('gh api -X PUT repos/o/r/pulls/7/requested_reviewers');
  passes('gh api --method PATCH repos/o/r/pulls/7');
  passes("gh api graphql -f query='{ viewer { login } }'");
});

test('git push --repo：位置參數全是 refspec', () => {
  asks('git push --repo=origin main');
  asks('git push --repo origin main');
  asks('git push --repo=origin', onMain);
  passes('git push --repo=origin feat/1-x');
  passes('git push --repo origin feat/1-x');
  passes('git push --repo=origin');
});

test('指令中切換目錄：以切換後的目錄判斷目前分支', () => {
  const byDir = { currentBranch: (dir) => ({ '/repo/main-wt': 'main', '/repo/feat-wt': 'feat/1-x' })[dir] ?? null };
  asks('cd /repo/main-wt && git push', byDir);
  asks('cd /repo && cd main-wt && git push origin HEAD', byDir);
  asks('pushd /repo/main-wt; git push', byDir);
  asks('bash -c "cd /repo/main-wt && git push"', byDir);
  asks('git -C /repo/main-wt push', byDir);
  passes('cd /repo/feat-wt && git push', byDir);
  passes('cd /repo/feat-wt && git push origin HEAD', byDir);
  passes('(cd /repo/main-wt && npm test) && git push', { ...byDir, cwd: '/repo/feat-wt' });
  passes('cd /repo/main-wt && git push origin feat/1-x', byDir);
});

test('指令中切換目錄：無法判斷切換後的分支時一律攔', () => {
  asks('cd "$REPO" && git push');
  asks('cd - && git push');
  asks('cd /repo/* && git push origin HEAD');
  asks('popd && git push');
  asks('cd /not-a-repo && git push', { currentBranch: () => null });
  asks('git --git-dir=/repo/.git push');
  passes('cd "$REPO" && git push origin feat/1-x');
});

const reason = (command, ctx = onFeature) => evaluate(command, ctx).reason;

test('訊息：目標確定是 main 時寫「即將推送到 main」', () => {
  assert.match(reason('git push origin main'), /^即將推送到 main/);
  assert.match(reason('git push', onMain), /^即將推送到 main/);
  assert.match(reason('git push --force origin main'), /^即將對 main 強制推送/);
  assert.match(reason('cd "$REPO" && git push origin main'), /^即將推送到 main/, '明寫 main 時即使切換過目錄也確定');
});

test('訊息：分支無法判斷時寫「無法判斷目標分支（可能是 main）」，不寫「即將推送到 main」', () => {
  for (const cmd of ['cd "$REPO" && git push', 'cd - && git push origin HEAD', 'popd && git push', 'git --git-dir=/repo/.git push']) {
    const r = reason(cmd);
    assert.match(r, /^無法判斷推送的目標分支/, cmd);
    assert.match(r, /可能是 main/, cmd);
    assert.doesNotMatch(r, /即將推送到 main/, cmd);
  }
  assert.match(reason('cd /not-a-repo && git push', { currentBranch: () => null }), /^無法判斷推送的目標分支/);
  assert.match(reason('cd "$REPO" && git push -f'), /^無法判斷強制推送的目標分支/);
  assert.match(reason('cd "$REPO" && git push origin +HEAD'), /^無法判斷強制推送的目標分支/);
});

const script = fileURLToPath(new URL('./confirm-main.mjs', import.meta.url));
const runHook = (input, env = {}) => {
  const { CLAUDE_CODE_REMOTE, ...rest } = process.env;
  return spawnSync(process.execPath, [script], { input, encoding: 'utf8', env: { ...rest, ...env } });
};

test('hook：本機推送 main 輸出 ask 與中文原因', () => {
  const r = runHook(JSON.stringify({ tool_name: 'Bash', tool_input: { command: 'git push origin main' } }));
  assert.equal(r.status, 0);
  const out = JSON.parse(r.stdout).hookSpecificOutput;
  assert.equal(out.hookEventName, 'PreToolUse');
  assert.equal(out.permissionDecision, 'ask');
  assert.match(out.permissionDecisionReason, /推送到 main/);
});

test('hook：本機（CLAUDE_CODE_REMOTE 未設定）合併類指令輸出 deny', () => {
  const merges = [
    'gh pr merge 3',
    'gh api -X PUT repos/o/r/pulls/7/merge',
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
  ];
  for (const command of merges) {
    const r = runHook(JSON.stringify({ tool_name: 'Bash', tool_input: { command } }));
    assert.equal(r.status, 0, command);
    const out = JSON.parse(r.stdout).hookSpecificOutput;
    assert.equal(out.permissionDecision, 'deny', command);
    assert.match(out.permissionDecisionReason, /^即將合併 PR/, command);
    assert.match(out.permissionDecisionReason, /決策中心經人授權.*GitHub 網頁合併/, command);
    assert.doesNotMatch(out.permissionDecisionReason, /請確認後再同意/, command);
  }
});

test('hook：其他指令不輸出決定、exit 0', () => {
  const r = runHook(JSON.stringify({ tool_name: 'Bash', tool_input: { command: 'git status' } }));
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
});

test('hook：輸入無法解析時不輸出決定、exit 0', () => {
  const r = runHook('not json');
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
});

test('decide：合併類指令在本機與雲端都 deny', () => {
  const envs = [{}, { CLAUDE_CODE_REMOTE: 'true' }, { CLAUDE_CODE_REMOTE: 'false' }, { CLAUDE_CODE_REMOTE: '1' }];
  const merges = [
    'gh pr merge 3',
    'gh api -X PUT repos/o/r/pulls/7/merge',
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
  ];
  for (const command of merges) {
    const result = evaluate(command);
    assert.equal(result.kind, 'merge', command);
    for (const env of envs) {
      const d = decide(result, env);
      assert.equal(d.permissionDecision, 'deny', `${command} ${JSON.stringify(env)}`);
      assert.equal(d.permissionDecisionReason, `${result.reason}${MERGE_DENY_NOTE}`);
    }
  }
  assert.equal(decide(evaluate('gh pr merge 3'), {}).permissionDecisionReason, `即將合併 PR（gh pr merge 3）。${MERGE_DENY_NOTE}`);
});

test('decide：推送 main 在 CLAUDE_CODE_REMOTE 為 true 時 deny，未設定或其他值時 ask', () => {
  const result = evaluate('git push origin main');
  assert.equal(result.kind, 'push');
  const remote = decide(result, { CLAUDE_CODE_REMOTE: 'true' });
  assert.equal(remote.permissionDecision, 'deny');
  assert.equal(remote.permissionDecisionReason, `即將推送到 main（git push origin main）。${REMOTE_DENY_NOTE}`);
  assert.doesNotMatch(remote.permissionDecisionReason, /請確認/);
  assert.deepEqual(decide(result, {}), { permissionDecision: 'ask', permissionDecisionReason: result.reason });
  for (const value of ['false', '1', 'TRUE', '']) {
    assert.equal(decide(result, { CLAUDE_CODE_REMOTE: value }).permissionDecision, 'ask', `CLAUDE_CODE_REMOTE=${JSON.stringify(value)}`);
  }
});

test('decide：雲端拒絕時各種攔截都保留攔了什麼', () => {
  const ctx = { currentBranch: () => null };
  const reasons = ['git push origin main', 'git push -f origin main', 'cd "$REPO" && git push']
    .map((c) => decide(evaluate(c, ctx), { CLAUDE_CODE_REMOTE: 'true' }).permissionDecisionReason);
  assert.match(reasons[0], /^即將推送到 main（git push origin main）。雲端 session 不執行/);
  assert.match(reasons[1], /^即將對 main 強制推送（git push -f origin main）。雲端 session 不執行/);
  assert.match(reasons[2], /^無法判斷推送的目標分支（git push），可能是 main。雲端 session 不執行/);
});

test('hook：雲端（CLAUDE_CODE_REMOTE=true）輸出 deny；其他指令仍不輸出', () => {
  const input = (command) => JSON.stringify({ tool_name: 'Bash', tool_input: { command } });
  const r = runHook(input('git push origin main'), { CLAUDE_CODE_REMOTE: 'true' });
  assert.equal(r.status, 0);
  const out = JSON.parse(r.stdout).hookSpecificOutput;
  assert.equal(out.permissionDecision, 'deny');
  assert.match(out.permissionDecisionReason, /雲端 session 不執行，推送 main 由人在 GitHub 進行/);
  const merge = JSON.parse(runHook(input('gh pr merge 3'), { CLAUDE_CODE_REMOTE: 'true' }).stdout).hookSpecificOutput;
  assert.equal(merge.permissionDecision, 'deny');
  assert.match(merge.permissionDecisionReason, /決策中心經人授權/);
  assert.equal(runHook(input('git status'), { CLAUDE_CODE_REMOTE: 'true' }).stdout, '');
});
