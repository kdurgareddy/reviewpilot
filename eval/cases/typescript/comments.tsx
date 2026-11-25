import React from "react";

export function Comment({ html }: { html: string }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />; // expect: security
}

export function setBio(el: HTMLElement, bio: string) {
  el.innerHTML = bio; // expect: security
}

export function setTitle(el: HTMLElement, title: string) {
  el.textContent = title;
}

export function isOwner(userId: string | number, ownerId: string) {
  return userId == ownerId; // expect: bug
}
