/** Office.js 브리지 — Task Pane(?embed=1)에서만 의미를 갖는다.
 *
 * office.js 는 index.html 이 embed 모드에서만 CDN 로드하므로, 일반 웹 방문자는
 * window.Office 가 없다 → 호출부는 officeAvailable() 로 버튼 노출을 게이트한다.
 *
 * 핵심: Document.getFileAsync(Compressed) 로 **열려 있는 워크북 바이트를 그대로**
 * 얻는다 → 다운로드→업로드 셔틀 없이 /api/xlsx/audit·import·diff 에 태운다
 * (docs/plan/addin_two_panel_ux.md §3 — 다리 2 해소). 서버 계약은 기존 xlsx_b64
 * 그대로라 백엔드 변경이 없다.
 */

/** Task Pane 안에서 Office 문서 컨텍스트가 살아있는가. */
export function officeAvailable() {
  return typeof window !== "undefined" && !!window.Office?.context?.document;
}

/** 셀 쓰기(Excel JS API)까지 가능한가 — Word/PowerPoint 호스트에는 `Excel` 이 없다. */
export function excelWriteAvailable() {
  return officeAvailable() && typeof window.Excel?.run === "function";
}

/** 2차원 배열 → 현재 선택 셀을 좌상단으로 기입한다(다리 1·3).
 *
 * 선택 영역의 **크기는 무시하고 시작 위치만** 쓴다 — 사용자가 한 셀만 찍어도 표 전체가
 * 들어가야 실용적이다. 덮어쓰기 위험이 있으므로 호출부가 확인 문구를 띄운다.
 * 값 타입은 그대로 전달한다(number 는 숫자 셀, string 은 텍스트) — 여기서 문자열로
 * 뭉개면 엑셀에서 계산이 안 되므로 숫자를 숫자로 유지하는 것이 계약이다.
 */
export function writeToSelection(rows) {
  return new Promise((resolve, reject) => {
    if (!excelWriteAvailable()) {
      reject(new Error("Excel Task Pane 에서만 사용할 수 있습니다."));
      return;
    }
    if (!rows?.length || !rows[0]?.length) {
      reject(new Error("보낼 데이터가 없습니다."));
      return;
    }
    const nRow = rows.length;
    const nCol = Math.max(...rows.map((r) => r.length));
    // 행마다 길이가 다르면 Excel 이 거부하므로 빈칸으로 패딩(오류 대신 정렬).
    const padded = rows.map((r) => (r.length === nCol ? r : [...r, ...Array(nCol - r.length).fill("")]));

    window.Excel.run(async (ctx) => {
      const sel = ctx.workbook.getSelectedRange();
      sel.load(["rowIndex", "columnIndex", "worksheet/name"]);
      await ctx.sync();
      const sheet = ctx.workbook.worksheets.getActiveWorksheet();
      const target = sheet.getRangeByIndexes(sel.rowIndex, sel.columnIndex, nRow, nCol);
      target.values = padded;
      target.format.autofitColumns();
      await ctx.sync();
      return { sheet: sel.worksheet.name, rows: nRow, cols: nCol };
    })
      .then(resolve)
      .catch((e) => {
        // 병합 셀·보호된 시트·표(ListObject) 경계가 대표적 실패 원인 — 원문을 함께 보인다.
        const m = e?.message || String(e);
        reject(new Error(
          m.includes("InvalidOperation") || m.includes("merge")
            ? `기입 실패 — 병합된 셀이나 보호된 영역일 수 있습니다: ${m}`
            : `기입 실패: ${m}`));
      });
  });
}

/** 임시 시트명 — 엑셀 시트명은 31자 제한이라 잘라 쓴다. `~` 접두는 작업 중 표식. */
function tempSheetName(name) {
  return `~${name}`.slice(0, 31);
}

/** 시트 플랜(서버 `excel/fs_sheet.plan_to_json`) → 워크북에 시트 생성·기입.
 *
 * `writeToSelection` 과 다른 점이 셋이다:
 *   ① **시트를 만든다** — 선택 위치가 아니라 이름이 정해진 시트(rFS·H_FS)에 쓴다.
 *   ② **수식을 쓴다** — `range.formulas` 로 넣으므로 '=' 로 시작하는 문자열은 살아있는
 *      수식이 된다. H_FS 는 전부 rFS 참조라, 값만 붙여넣으면 존재 이유가 사라진다.
 *   ③ **같은 이름 시트가 있으면 교체한다** — 재조회 시 옛 행이 남아 체크행의 범위가
 *      어긋나는 것을 막는다. 파괴적이므로 호출부가 확인 문구를 띄운다.
 *
 * ⚠️ **원자성(2026-08-04 수정)**: 이전 구현은 `delete()` → `add()` 순서였다. Office.js
 * 는 배치를 큐에 넣고 `sync()` 에서 적용하는데 **트랜잭션 보장이 문서화돼 있지 않아**,
 * 중간 실패(보호된 시트·이름 충돌·사용자 취소)면 **삭제만 적용된 상태**가 남을 수 있다
 * — 재생성 가능한 데이터 시트면 재조회로 복구되지만, 원장(유일본)에서는 조서가
 * 통째로 사라진다. 이제 **임시 시트에 전량 기입 → sync(커밋 지점) → 원본 삭제 →
 * 이름 교체** 순서다. 커밋 지점 이전에 실패하면 원본이 그대로 살아있다.
 *
 * ⚠️ **파티션 강제**: `readonly_hint` 시트(rFS = 공시 원문 원자료)는 기입 후 시트
 * 보호를 건다. 지금까지 '수정금지'는 규약일 뿐이라 사람이 고치면 H_FS 의 Refer Check
 * 행이 **바뀐 기준선과 비교**해 조용히 무의미해졌다. 규약을 불변식으로 바꾼다.
 * 재기입 시에는 삭제 전에 보호를 해제한다(보호된 시트는 지워지지 않는다).
 *
 * 시트는 플랜 순서대로, **한 장씩 최종 이름까지 확정하고** 다음 장으로 간다 —
 * H_FS 가 rFS 를 이름으로 참조하므로 원문 시트가 임시 이름인 채로 남아 있으면
 * 수식이 깨진다.
 */
export function writeSheetPlan(plan) {
  return new Promise((resolve, reject) => {
    if (!excelWriteAvailable()) {
      reject(new Error("Excel Task Pane 에서만 사용할 수 있습니다."));
      return;
    }
    const sheets = plan?.sheets || [];
    if (!sheets.length) {
      reject(new Error("기입할 시트가 없습니다."));
      return;
    }
    window.Excel.run(async (ctx) => {
      const book = ctx.workbook.worksheets;
      book.load("items/name");
      await ctx.sync();
      const existing = new Set(book.items.map((s) => s.name));

      const written = [];
      for (const sp of sheets) {
        const tmp = tempSheetName(sp.name);
        const old = existing.has(sp.name) ? book.getItem(sp.name) : null;
        const stale = existing.has(tmp) ? book.getItem(tmp) : null;
        // 보호 여부는 미리 읽어둔다 — 보호된 시트는 delete 가 실패한다.
        if (old) old.load("protection/protected");
        if (stale) stale.load("protection/protected");
        if (old || stale) await ctx.sync();

        if (stale) {                       // 이전 실패로 남은 임시 시트 회수
          if (stale.protection.protected) stale.protection.unprotect();
          stale.delete();
          await ctx.sync();
          existing.delete(tmp);
        }

        // ── 임시 시트에 전량 기입(원본은 아직 그대로) ──
        const sh = book.add(tmp);
        const nRow = sp.rows.length;
        const nCol = Math.max(...sp.rows.map((r) => r.length), 1);
        // 행 길이를 맞춘다 — 들쭉날쭉하면 Excel 이 범위 기입을 거부한다.
        const grid = sp.rows.map((r) =>
          r.length === nCol ? r : [...r, ...Array(nCol - r.length).fill("")]);
        // values 가 아니라 formulas 로 넣는다(수식 보존).
        sh.getRangeByIndexes(0, 0, nRow, nCol).formulas = grid;
        if (sp.widths?.length) {
          sp.widths.forEach((w, i) => {
            if (i < nCol) sh.getRangeByIndexes(0, i, 1, 1).format.columnWidth = w * 7;
          });
        } else {
          sh.getUsedRange().format.autofitColumns();
        }
        for (const r of sp.bold_rows || []) {
          if (r >= 1 && r <= nRow) sh.getRangeByIndexes(r - 1, 0, 1, nCol).format.font.bold = true;
        }
        if (sp.freeze) {
          const m = /^([A-Z]+)(\d+)$/.exec(sp.freeze);
          if (m) sh.freezePanes.freezeRows(Number(m[2]) - 1);
        }
        await ctx.sync();                  // ★ 커밋 지점 — 여기까지 성공해야 원본을 건드린다

        // ── 교체: 원본 삭제 → (sync) → 이름 승격 ──
        // ⚠️ 삭제와 개명을 **한 배치에 넣지 않는다** — 같은 이름을 지우면서 동시에
        // 그 이름으로 바꾸면 호스트가 ItemAlreadyExists 로 거부하는 경우가 있다.
        if (old) {
          if (old.protection.protected) old.protection.unprotect();
          old.delete();
          await ctx.sync();
        }
        sh.name = sp.name;
        await ctx.sync();
        existing.add(sp.name);

        // 보호는 **선택적 강화**다 — 실패해도 기입 자체를 잃지 않는다.
        // (호스트·라이선스에 따라 protect 가 거부될 수 있는데, 그것 때문에 시트 생성이
        //  통째로 실패하면 본말이 전도된다. 대신 보호 여부를 결과에 실어 알린다.)
        let locked = false;
        if (sp.readonly_hint) {
          try {
            sh.protection.protect();
            await ctx.sync();
            locked = true;
          } catch {
            // 보호 실패는 삼키되 조용히 넘어가지 않는다 — 호출부가 결과로 안다.
          }
        }
        written.push({ name: sp.name, rows: nRow, cols: nCol, protected: locked });
      }
      // 마지막 시트(H_FS)를 활성화 — 사용자가 결과를 바로 본다.
      book.getItem(sheets[sheets.length - 1].name).activate();
      await ctx.sync();
      return written;
    })
      .then(resolve)
      .catch((e) => {
        const m = e?.message || String(e);
        reject(new Error(
          m.includes("InvalidArgument") || m.includes("ItemAlreadyExists")
            ? `시트 생성 실패 — 시트 이름이 이미 쓰이고 있거나 보호되어 있습니다: ${m}`
            : `시트 기입 실패: ${m}`));
      });
  });
}

/** 들쭉날쭉한 행들을 직사각형으로 — Excel 은 길이가 다른 행 배열을 거부한다. */
function padGrid(rows) {
  const nCol = Math.max(...rows.map((r) => r.length), 1);
  return {
    nRow: rows.length, nCol,
    grid: rows.map((r) => (r.length === nCol ? r : [...r, ...Array(nCol - r.length).fill("")])),
  };
}

/** 시트 격자 읽기 — 시트가 없거나 비었으면 `[]`.
 *
 * 공유 원장은 "있으면 이어 쓰고 없으면 만든다"라, 쓰기 전에 현재 내용을 알아야 한다.
 * 서버가 그 격자를 fold 해서 **바뀐 것만** 새 행으로 돌려준다(append-only).
 */
export function readSheetGrid(name) {
  return new Promise((resolve, reject) => {
    if (!excelWriteAvailable()) {
      reject(new Error("Excel Task Pane 에서만 사용할 수 있습니다."));
      return;
    }
    window.Excel.run(async (ctx) => {
      const sh = ctx.workbook.worksheets.getItemOrNullObject(name);
      sh.load("isNullObject");
      await ctx.sync();
      if (sh.isNullObject) return [];
      const used = sh.getUsedRangeOrNullObject();
      used.load(["values", "isNullObject"]);
      await ctx.sync();
      return used.isNullObject ? [] : used.values;
    })
      .then(resolve)
      .catch((e) => reject(new Error(`시트 읽기 실패(${name}): ${e?.message || e}`)));
  });
}

/** 사실 원장 append — 서버 계획(`/api/facts/append-plan`)을 그대로 기입한다.
 *
 * `writeSheetPlan` 과 결정적으로 다르다: **지우지 않는다.** 원장은 유일본이고 이력
 * 자체가 산출물이라, 재생성 모델(delete→add)을 쓰면 조서가 사라진다. 헤더는 시트가
 * 비어 있을 때만 쓰고, 이후에는 마지막 행 다음에 이어 붙인다.
 *
 * 소유권(단일 작성자)을 시트 보호로 강제한다 — 쓰기 직전 해제, 쓴 뒤 재보호.
 */
export function appendFactRows(plan) {
  return new Promise((resolve, reject) => {
    if (!excelWriteAvailable()) {
      reject(new Error("Excel Task Pane 에서만 사용할 수 있습니다."));
      return;
    }
    if (plan?.blocked) {
      reject(new Error(plan.reason || "원장에 기록할 수 없습니다."));
      return;
    }
    if (!plan?.rows?.length && !plan?.create) {
      resolve({ written: 0, sheet: plan?.sheet });
      return;
    }
    window.Excel.run(async (ctx) => {
      const book = ctx.workbook.worksheets;
      const probe = book.getItemOrNullObject(plan.sheet);
      probe.load("isNullObject");
      await ctx.sync();

      let sh;
      if (probe.isNullObject) {
        sh = book.add(plan.sheet);
      } else {
        sh = book.getItem(plan.sheet);
        sh.load("protection/protected");
        await ctx.sync();
        if (sh.protection.protected) sh.protection.unprotect();
      }

      if (plan.create && plan.header_rows?.length) {
        const h = padGrid(plan.header_rows);
        sh.getRangeByIndexes(0, 0, h.nRow, h.nCol).values = h.grid;
        sh.getRangeByIndexes(h.nRow - 1, 0, 1, h.nCol).format.font.bold = true;
      }
      if (plan.rows.length) {
        const b = padGrid(plan.rows);
        // start_row 는 1-based → 인덱스는 -1.
        sh.getRangeByIndexes(plan.start_row - 1, 0, b.nRow, b.nCol).values = b.grid;
      }
      sh.getUsedRange().format.autofitColumns();
      sh.protection.protect();
      await ctx.sync();
      return { written: plan.rows.length, sheet: plan.sheet, created: !!plan.create };
    })
      .then(resolve)
      .catch((e) => reject(new Error(`원장 기록 실패(${plan?.sheet}): ${e?.message || e}`)));
  });
}

/** 슬라이스 바이트(number[])들을 base64 로. btoa 인자 한계 때문에 청크로 이어붙인다. */
function slicesToBase64(slices) {
  let bin = "";
  for (const data of slices) {
    const bytes = data instanceof Uint8Array ? data : Uint8Array.from(data);
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
  }
  return btoa(bin);
}

/** 특정 셀에 수식을 기입한다(재연결 제안 적용 — 다리 3의 셀 단위 버전).
 *
 * writeToSelection 과 달리 **주소를 명시**한다: 재연결은 "그 상수 셀"을 정확히
 * 겨냥해야 하고, 사용자가 다른 셀을 선택해둔 상태에서 눌러도 엉뚱한 곳을 덮으면
 * 안 된다. 덮어쓰기이므로 호출부가 확인 문구를 띄운다.
 */
export function writeFormula(sheetName, ref, formula) {
  return new Promise((resolve, reject) => {
    if (!excelWriteAvailable()) {
      reject(new Error("Excel Task Pane 에서만 사용할 수 있습니다."));
      return;
    }
    window.Excel.run(async (ctx) => {
      const sh = ctx.workbook.worksheets.getItem(sheetName);
      const r = sh.getRange(ref);
      r.formulas = [[formula]];
      await ctx.sync();
    })
      .then(() => resolve({ sheet: sheetName, ref }))
      .catch((e) => reject(new Error(
        `수식 기입 실패(${sheetName}!${ref}): ${e?.message || e}` +
        " — 시트 이름·보호 상태를 확인하세요.")));
  });
}

/** 현재 워크북(.xlsx) → base64. 실패는 한국어 메시지 Error 로 던진다. */
export function currentWorkbookB64() {
  return new Promise((resolve, reject) => {
    const Office = window.Office;
    const doc = Office?.context?.document;
    if (!doc) {
      reject(new Error("Office 컨텍스트 없음 — Excel Task Pane 에서만 사용할 수 있습니다."));
      return;
    }
    doc.getFileAsync(Office.FileType.Compressed, { sliceSize: 65536 }, (res) => {
      if (res.status !== Office.AsyncResultStatus.Succeeded) {
        reject(new Error(res.error?.message || "getFileAsync 실패 — manifest 권한(ReadWriteDocument)을 확인하세요."));
        return;
      }
      const file = res.value;
      const slices = new Array(file.sliceCount);
      // 슬라이스는 순차로 읽는다(동시 요청은 호스트가 거부할 수 있음).
      const readSlice = (i) => {
        if (i >= file.sliceCount) {
          file.closeAsync(() => {});
          try {
            resolve(slicesToBase64(slices));
          } catch (e) {
            reject(new Error(`워크북 인코딩 실패: ${e.message}`));
          }
          return;
        }
        file.getSliceAsync(i, (sr) => {
          if (sr.status !== Office.AsyncResultStatus.Succeeded) {
            file.closeAsync(() => {});
            reject(new Error(sr.error?.message || `워크북 슬라이스 ${i} 읽기 실패`));
            return;
          }
          slices[i] = sr.value.data;
          readSlice(i + 1);
        });
      };
      readSlice(0);
    });
  });
}
