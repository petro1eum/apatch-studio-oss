import contract from "./navigation.contract.json";

export type OutsideInViewId = "home" | "backlog" | "library" | "admin" | "inbox";

export interface OutsideInRoute {
  view: OutsideInViewId;
  section: string;
  resourceId: string | null;
}

export interface OutsideInNavigationTarget {
  id: OutsideInViewId;
  label: string;
  availability: "all" | "configured";
  default_section: string;
  sections: string[];
}

export const outsideInNavigationTargets =
  contract.targets as OutsideInNavigationTarget[];

const targets = new Map(outsideInNavigationTargets.map((item) => [item.id, item]));
const legacyRoutes = contract.legacy_routes as Record<string, string>;

function decode(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function mapLegacy(parts: string[]) {
  const keys = Object.keys(legacyRoutes).sort(
    (left, right) => right.split("/").length - left.split("/").length,
  );
  for (const key of keys) {
    const prefix = key.split("/");
    if (prefix.every((part, index) => parts[index] === part)) {
      return [...legacyRoutes[key].split("/"), ...parts.slice(prefix.length)];
    }
  }
  return parts;
}

export function parseOutsideInHash(hash: string): OutsideInRoute {
  const raw = hash
    .replace(/^#\/?/, "")
    .split("/")
    .filter(Boolean)
    .map(decode);
  const mapped = mapLegacy(raw.length ? raw : [contract.default_route]);
  const candidate = mapped[0] as OutsideInViewId;
  const target = targets.get(candidate) ?? targets.get("home")!;
  let section = target.default_section;
  let offset = 1;
  if (mapped[1] && target.sections.includes(mapped[1])) {
    section = mapped[1];
    offset = 2;
  }
  return {
    view: target.id,
    section,
    resourceId: mapped.slice(offset).join("/") || null,
  };
}

export function outsideInRouteHash(route: OutsideInRoute) {
  const target = targets.get(route.view) ?? targets.get("home")!;
  const parts: string[] = [target.id];
  if (route.section !== target.default_section) parts.push(route.section);
  if (route.resourceId) parts.push(encodeURIComponent(route.resourceId));
  return "#/" + parts.join("/");
}

export function canonicalOutsideInHash(hash: string) {
  return outsideInRouteHash(parseOutsideInHash(hash));
}
