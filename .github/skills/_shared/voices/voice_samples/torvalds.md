# torvalds — real-text samples

- Person: Linus Torvalds
- Register: written posts — a forum argument and a release announcement; his typos preserved verbatim, shortlogs omitted, "Linus" sign-offs trimmed so the name stays out of writer prompts
- Source for Excerpt 1: RealWorldTech forum thread "Alder Lake and AVX-512", July 11, 2020; https://www.realworldtech.com/forum/?threadid=193189&curpostid=193190 (RealWorldTech serves plain HTML, fetch-friendly)
- Source for Excerpt 2: "Linux 6.14", LKML, March 24, 2025; https://lkml.iu.edu/hypermail/linux/kernel/2503.3/00718.html (the IU hypermail mirror serves plain HTML with no bot challenge — best fetch route for LKML samples)
- Rights: public forum and mailing-list posts

## Excerpt 1

I hope AVX512 dies a painful death, and that Intel starts fixing real problems instead of trying to create magic instructions to then create benchmarks that they can look good on.

I hope Intel gets back to basics: gets their process working again, and concentrate more on regular code that isn't HPC or some other pointless special case.

I've said this before, and I'll say it again: in the heyday of x86, when Intel was laughing all the way to the bank and killing all their competition, absolutely everybody else did better than Intel on FP loads. Intel's FP performance sucked (relatively speaking), and it matter not one iota.

Because absolutely nobody cares outside of benchmarks.

The same is largely true of AVX512 now - and in the future. Yes, you can find things that care. No, those things don't sell machines in the big picture.

## Excerpt 2

So it's early Monday morning (well - early for me, I'm not really a morning person), and I'd love to have some good excuse for why I didn't do the 6.14 release yesterday on my regular Sunday afternoon release schedule.

I'd like to say that some important last-minute thing came up and delayed things.

But no. It's just pure incompetence.

Because absolutely nothing last-minute happened yesterday, and I was just clearing up some unrelated things in order to be ready for the merge window. And in the process just entirely forgot to actually ever cut the release. D'oh.

So yes, a little delayed for no good reason at all, and obviously that means that the merge window has opened. No rest for the wicked (or the incompetent).

Below is the shortlog for the last week. It's nice and small - not only was there no last-minute issue yesterday, the whole last week was pretty calm. The patch is dominated by some amd gpu updates, and even those are pretty small. The rest is random small changes all over.

Judging by my pending pile of pull requests, 6.15 will be much busier.
