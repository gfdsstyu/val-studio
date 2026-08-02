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
