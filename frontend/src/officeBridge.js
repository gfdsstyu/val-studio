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
