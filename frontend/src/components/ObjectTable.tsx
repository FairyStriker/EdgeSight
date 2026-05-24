import { useLayoutEffect, useRef } from "react";
import type { DetectedObject, Lang } from "../api/types";
import { t } from "../i18n";

interface Props {
  lang: Lang;
  objects: DetectedObject[];
}

export function ObjectTable({ lang, objects }: Props) {
  // 매 WebSocket 갱신 시 row 재구성으로 scrollTop이 0으로 튕기는 문제 해결.
  // 사용자가 스크롤한 위치를 ref에 저장 → 매 렌더 직후 복원.
  const wrapperRef = useRef<HTMLDivElement>(null);
  const savedScrollTop = useRef(0);

  useLayoutEffect(() => {
    if (wrapperRef.current) {
      wrapperRef.current.scrollTop = savedScrollTop.current;
    }
  });

  const onScroll = () => {
    if (wrapperRef.current) {
      savedScrollTop.current = wrapperRef.current.scrollTop;
    }
  };

  return (
    <div ref={wrapperRef} className="table-wrapper" onScroll={onScroll}>
      <table>
        <thead>
          <tr>
            <th>{t(lang, "th_id")}</th>
            <th>{t(lang, "th_class")}</th>
            <th>{t(lang, "th_conf")}</th>
            <th>{t(lang, "th_box")}</th>
          </tr>
        </thead>
        <tbody>
          {objects.length > 0 ? (
            objects.map((obj) => (
              <tr key={`${obj.id}-${obj.label}`}>
                <td>{obj.id}</td>
                <td>{obj.label}</td>
                <td>{Math.round(obj.confidence * 100)}%</td>
                <td>[{obj.bbox.join(",")}]</td>
              </tr>
            ))
          ) : (
            <tr>
              <td
                colSpan={4}
                style={{ textAlign: "center", padding: 20, color: "#ccc" }}
              >
                {t(lang, "msg_waiting").replace("...", "")}(0)
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
