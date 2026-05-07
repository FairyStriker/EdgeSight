import type { DetectedObject, Lang } from "../api/types";
import { t } from "../i18n";

interface Props {
  lang: Lang;
  objects: DetectedObject[];
}

export function ObjectTable({ lang, objects }: Props) {
  return (
    <div className="table-wrapper">
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
