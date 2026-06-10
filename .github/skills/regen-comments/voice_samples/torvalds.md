# torvalds — real-text samples

- Person: Linus Torvalds
- Register: written public mailing-list release announcements; shortlogs omitted and "Linus" sign-offs trimmed so the name stays out of writer prompts
- Source for Excerpt 1: "Linux 6.0", LKML, October 2, 2022; https://lkml.org/lkml/2022/10/2/255 (fetched via Wayback Machine; lkml.org and lore.kernel.org challenge automated fetches)
- Source for Excerpt 2: "Linux 6.14", LKML, March 24, 2025; https://lkml.iu.edu/hypermail/linux/kernel/2503.3/00718.html (the IU hypermail mirror serves plain HTML with no bot challenge — best fetch route for future LKML samples)
- Rights: public mailing-list posts

## Excerpt 1

So, as is hopefully clear to everybody, the major version number change is more about me running out of fingers and toes than it is about any big fundamental changes.

But of course there's a lot of various changes in 6.0 - we've got over 15k non-merge commits in there in total, after all, and as such 6.0 is one of the bigger releases at least in numbers of commits in a while.

The shortlog of changes below is only the last week since 6.0-rc7. A little bit of everything, although the diffstat is dominated by drm (mostly amd new chip support) and networking drivers.

And this obviously means that tomorrow I'll open the merge window for 6.1. Which - unlike 6.0 - has a number of fairly core new things lined up. But for now, please do give this most recent kernel version a whirl,

## Excerpt 2

So it's early Monday morning (well - early for me, I'm not really a morning person), and I'd love to have some good excuse for why I didn't do the 6.14 release yesterday on my regular Sunday afternoon release schedule.

I'd like to say that some important last-minute thing came up and delayed things.

But no. It's just pure incompetence.

Because absolutely nothing last-minute happened yesterday, and I was just clearing up some unrelated things in order to be ready for the merge window. And in the process just entirely forgot to actually ever cut the release. D'oh.

So yes, a little delayed for no good reason at all, and obviously that means that the merge window has opened. No rest for the wicked (or the incompetent).

Below is the shortlog for the last week. It's nice and small - not only was there no last-minute issue yesterday, the whole last week was pretty calm. The patch is dominated by some amd gpu updates, and even those are pretty small. The rest is random small changes all over.

Judging by my pending pile of pull requests, 6.15 will be much busier.
