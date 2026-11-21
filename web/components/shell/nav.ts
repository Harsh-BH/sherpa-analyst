import { Compass, FlaskConical, History, MessageSquare } from "lucide-react";

/** The app's pages: the sidebar nav and the command palette's Pages group. */
export const NAV = [
  { href: "/", label: "Ask", icon: MessageSquare },
  { href: "/explore", label: "Explore", icon: Compass },
  { href: "/eval", label: "Eval", icon: FlaskConical },
  { href: "/runs", label: "Runs", icon: History },
];
