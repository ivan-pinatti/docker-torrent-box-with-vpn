# Contributing

I would love your inputs and ideas! My goal is to make contributing to this
project as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features
- Becoming a maintainer

## Github Rocks

Everything is hosted in Github, issue tracking, feature requests, as well as accept pull requests.

## Github Flow

This project uses [Github Flow](https://guides.github.com/introduction/flow/index.html),
so all code changes happen through pull requests.

Pull requests are the best way to propose changes to the codebase. I actively
welcome your pull requests:

1. Fork the repo and create your branch from `main`.
2. If you don't have it yet, please install pre-commit. More info:
   <https://pre-commit.com/>
3. After pre-commit is installed, add the hooks by running `pre-commit install`.
4. MegaLinter runs incrementally at `pre-commit` and as a broader gate at
   `pre-push`, while the focused hooks still run directly in `pre-commit`.
5. Pull requests also run the MegaLinter workflow in GitHub Actions, so the same
   checks are enforced even if local hooks are not installed.
6. For a full repository pass, run
   `pre-commit run megalinter-full --hook-stage pre-push --all-files`.
7. Adhere to the commit message guidelines as this repository uses
   [semantic versioning](https://semver.org/). More info:
   <https://github.com/mathieudutour/github-tag-action#bumping>
8. At the moment the repository doesn't have automated testing, therefore test
   manually that your changes are not breaking anything.
9. Update the documentation accordingly
10. Issue the pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be
under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers
the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](https://github.com/briandk/transcriptase-atom/issues)

I use GitHub issues to track public bugs. Report a bug by
[opening a new issue](https://github.com/ivan-pinatti/docker-torrent-box-with-vpn/issues/new);
it's that easy!

## Write bug reports with detail, background, and sample code

[This is an example](http://stackoverflow.com/q/12488905/180626) of a bug
report I wrote, and I think it's not a bad model. Here's
[another example from Craig Hockenberry](http://www.openradar.me/11905408), an
app developer whom I greatly respect.

## Use a Consistent Coding Style

The repository is already using some tools to help with that. Make sure you are
running the pre-commit hooks and allowing MegaLinter to run both locally and in
pull requests before sending changes upstream.

- 2 spaces for indentation rather than tabs
- You can try running `pre-commit run -a` for style unification
- Use `pre-commit run megalinter-full --hook-stage pre-push --all-files` when
  you need the full repository security/IaC pass locally

## License

By contributing, you agree that your contributions will be licensed under its MIT License.

## References

This document was adapted from the Github Gist <https://gist.github.com/briandk/3d2e8b3ec8daf5a27a62>
