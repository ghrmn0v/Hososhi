'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

/**
 * Top navigation.
 *
 * The active tab uses the designer's slash effect: two copies of the label clipped by a
 * diagonal, with a tapered red blade crossing the cut. It plays once when a tab becomes
 * active and is disabled under prefers-reduced-motion (the final cut is still shown).
 */
export function TopNav() {
  const pathname = usePathname();

  const tabsBefore = [
    { href: '/', label: 'Overview' },
    { href: '/workflows', label: 'Workflows' },
  ];

  const tabsAfter = [
    { href: '/automation', label: 'Automation' },
    { href: '/activity', label: 'Activity' },
  ];

  return (
    <nav className="top">
      <div className="nav-group left">
        {tabsBefore.map((tab) => (
          <NavTab key={tab.href} {...tab} active={isActive(pathname, tab.href)} />
        ))}
      </div>

      <Link className="brand" href="/">
        {/* Logo from the designer handoff: workflowplan/04_FRONTEND/ui/screens/hososhi-mark.png */}
        <img src="/hososhi-mark.png" alt="" width={36} height={36} />
        <b>HOSOSHI</b>
      </Link>

      <div className="nav-group right">
        {tabsAfter.map((tab) => (
          <NavTab key={tab.href} {...tab} active={isActive(pathname, tab.href)} />
        ))}
      </div>
    </nav>
  );
}

function NavTab({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active: boolean;
}) {
  // Inactive: plain tab. Active: tab with .cut class — both share identical margin (0 5px)
  // so dimensions never change when switching. The animation only plays on .cut.
  if (!active) {
    return (
      <Link className="tab" href={href}>
        {label}
      </Link>
    );
  }

  return (
    <Link className="tab cut" href={href} aria-current="page">
      <span className="ca">{label}</span>
      <span className="cb" aria-hidden="true">
        {label}
      </span>
      <i aria-hidden="true" />
    </Link>
  );
}

/**
 * Exactly one tab is active at a time.
 *
 * Automation and Activity have their own top-level routes, so the workflow screens
 * below /workflows must not light up the Workflows tab while an automation or run
 * screen is open.
 */
function isActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  if (href === '/workflows') {
    return (
      pathname === '/workflows' ||
      (pathname.startsWith('/workflows/') && !pathname.includes('/automation'))
    );
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The sawtooth rule between the nav and the content. */
export function Sawtooth() {
  return <div className="sg" aria-hidden="true" />;
}

export function Breadcrumb({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <div className="bc">
      {items.map((item, i) => {
        const last = i === items.length - 1;
        return (
          <span key={`${item.label}-${i}`}>
            {item.href && !last ? (
              <Link href={item.href}>{item.label}</Link>
            ) : last ? (
              <b>{item.label}</b>
            ) : (
              <span>{item.label}</span>
            )}
            {!last ? ' / ' : null}
          </span>
        );
      })}
    </div>
  );
}