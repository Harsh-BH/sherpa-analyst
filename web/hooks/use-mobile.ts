import * as React from "react"

const MOBILE_BREAKPOINT = 768

/** A CSS media query as state; `serverValue` is what the server render and hydration assume. */
export function useMediaQuery(query: string, serverValue: boolean) {
  const subscribe = React.useCallback(
    (onChange: () => void) => {
      const mql = window.matchMedia(query)
      mql.addEventListener("change", onChange)
      return () => mql.removeEventListener("change", onChange)
    },
    [query]
  )
  return React.useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => serverValue)
}

export function useIsMobile() {
  return useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`, false)
}
