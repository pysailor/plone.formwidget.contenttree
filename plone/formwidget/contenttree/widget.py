from AccessControl import getSecurityManager
from Acquisition import Explicit
from Acquisition.interfaces import IAcquirer

from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.interface import implementsOnly, implementer
from zope.component import getMultiAdapter
from zope.i18n import translate

import z3c.form.interfaces
import z3c.form.widget
import z3c.form.util

from zope.app.component.hooks import getSite

from plone.app.layout.navigation.interfaces import INavtreeStrategy
from plone.app.layout.navigation.navtree import buildFolderTree

from plone.formwidget.autocomplete.widget import \
     AutocompleteSelectionWidget, AutocompleteMultiSelectionWidget

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView

from plone.formwidget.contenttree.interfaces import IContentTreeWidget


class Fetch(BrowserView):

    fragment_template = ViewPageTemplateFile('fragment.pt')
    recurse_template = ViewPageTemplateFile('input_recurse.pt')

    def validate_access(self):

        content = self.context.form.context

        # If the object is not wrapped in an acquisition chain
        # we cannot check any permission.
        if not IAcquirer.providedBy(content):
            return
        
        url = self.request.getURL()
        view_name = url[len(content.absolute_url()):].split('/')[1]
        
        # May raise Unauthorized

        # If the view is 'edit', then traversal prefers the view and
        # restrictedTraverse prefers the edit() method present on most CMF
        # content. Sigh...
        if not view_name.startswith('@@') and not view_name.startswith('++'):
            view_name = '@@' + view_name

        view_instance = content.restrictedTraverse(view_name)
        getSecurityManager().validate(content, content, view_name,
                                      view_instance)

    def __call__(self):

        # We want to check that the user was indeed allowed to access the
        # form for this widget. We can only this now, since security isn't
        # applied yet during traversal.
        self.validate_access()

        widget = self.context
        context = widget.context

        # Update the widget before accessing the source.
        # The source was only bound without security applied
        # during traversal before.
        widget.update()
        source = widget.bound_source

        directory = self.request.form.get('href', None)
        level = self.request.form.get('rel', 0)

        navtree_query = source.navigation_tree_query.copy()
        navtree_query['path'] = {'depth': 1, 'query': directory}

        if 'is_default_page' not in navtree_query:
            navtree_query['is_default_page'] = False

        content = context
        if not IAcquirer.providedBy(content):
            content = getSite()
        
        strategy = getMultiAdapter((content, widget), INavtreeStrategy)
        catalog = getToolByName(content, 'portal_catalog')

        children = []
        for brain in catalog(navtree_query):
            newNode = {'item'          : brain,
                       'depth'         : -1, # not needed here
                       'currentItem'   : False,
                       'currentParent' : False,
                       'children'      : []}
            if strategy.nodeFilter(newNode):
                newNode = strategy.decoratorFactory(newNode)
                children.append(newNode)

        return self.fragment_template(children=children, level=int(level))


class ContentTreeBase(Explicit):
    implementsOnly(IContentTreeWidget)

    # XXX: Due to the way the rendering of the QuerySourceRadioWidget works,
    # if we call this 'template' or use a <z3c:widgetTemplate /> directive,
    # we'll get infinite recursion when trying to render the radio buttons.

    input_template = ViewPageTemplateFile('input.pt')
    hidden_template = ViewPageTemplateFile('hidden.pt')
    display_template = None # set by subclass
    recurse_template = ViewPageTemplateFile('input_recurse.pt')

    # Parameters passed to the JavaScript function
    folderEvent = 'click'
    selectEvent = 'click'
    expandSpeed = 200
    collapseSpeed = 200
    multiFolder = True
    multi_select = False

    # Overrides for autocomplete widget
    formatItem = ('function(row, idx, count, value) {'
                  '  return row[1] + " (" + row[0] + ")"; }')

    def brain_to_token(self,brain):
        # Using an attribute as a token, fetch that
        if getattr(self,'token_attribute',None):
            return getattr(brain,getattr(self, 'token_attribute'))
        # Fall back to fetching path
        if not(hasattr(self,'portal_path')):
            content = self.context
            if not IAcquirer.providedBy(content):
                content = getSite()
            portal_tool = getToolByName(content, "portal_url")
            self.portal_path = portal_tool.getPortalPath()
        return brain.getPath()[len(self.portal_path):]

    def render_tree(self):
        content = self.context
        if not IAcquirer.providedBy(content):
            content = getSite()

        source = self.bound_source

        strategy = getMultiAdapter((content, self), INavtreeStrategy)
        data = buildFolderTree(content,
                               obj=content,
                               query=source.navigation_tree_query,
                               strategy=strategy)

        return self.recurse_template(children=data.get('children', []), level=1)

    def render(self):
        if self.mode == z3c.form.interfaces.DISPLAY_MODE:
            # Don't set token_attribute, since we want to render useful links
            return self.display_template(self)
        elif self.mode == z3c.form.interfaces.HIDDEN_MODE:
            self.token_attribute = getattr(self.bound_source,'token_attribute',None)
            return self.hidden_template(self)
        else:
            self.token_attribute = getattr(self.bound_source,'token_attribute',None)
            return self.input_template(self)

    def contenttree_url(self):
        form_url = self.request.getURL()

        form_prefix = self.form.prefix + self.__parent__.prefix
        widget_name = self.name[len(form_prefix):]
        return "%s/++widget++%s/@@contenttree-fetch" % (form_url, widget_name,)

    def js_extra(self):
        return """\

                $('#%(id)s-widgets-query').after(function() {
                    if($(this).siblings('input.searchButton').length > 0) { return; }
                    return $(document.createElement('input'))
                        .attr({
                            'type': 'button',
                            'value': '%(button_val)s'
                        })
                        .addClass('searchButton')
                        .click( function () {
                            var parent = $(this).parents("*[id$='-autocomplete']")
                            var window = parent.siblings("*[id$='-contenttree-window']")
                            window.showDialog();
                        })
                });
                $('#%(id)s-contenttree-window').find('.contentTreeAdd').unbind('click').click(function () {
                    $(this).contentTreeAdd();
                });
                $('#%(id)s-contenttree-window').find('.contentTreeCancel').unbind('click').click(function () {
                    $(this).contentTreeCancel();
                });
                $('#%(id)s-widgets-query').after(" ");
                $('#%(id)s-contenttree').contentTree(
                    {
                        script: '%(url)s',
                        folderEvent: '%(folderEvent)s',
                        selectEvent: '%(selectEvent)s',
                        expandSpeed: %(expandSpeed)d,
                        collapseSpeed: %(collapseSpeed)s,
                        multiFolder: %(multiFolder)s,
                        multiSelect: %(multiSelect)s,
                    },
                    function(event, selected, data, title) {
                        // alert(event + ', ' + selected + ', ' + data + ', ' + title);
                    }
                );
        """ % dict(url=self.contenttree_url(),
                   id=self.name.replace('.', '-'),
                   folderEvent=self.folderEvent,
                   selectEvent=self.selectEvent,
                   expandSpeed=self.expandSpeed,
                   collapseSpeed=self.collapseSpeed,
                   multiFolder=str(self.multiFolder).lower(),
                   multiSelect=str(self.multi_select).lower(),
                   name=self.name,
                   klass=self.klass,
                   title=self.title,
                   button_val=translate(
                       u'label_contenttree_browse',
                       default=u'browse...',
                       domain='plone.formwidget.contenttree',
                       context=self.request))


class ContentTreeWidget(ContentTreeBase, AutocompleteSelectionWidget):
    """ContentTree widget that allows single selection.
    """

    klass = u"contenttree-widget"
    display_template = ViewPageTemplateFile('display_single.pt')


class MultiContentTreeWidget(ContentTreeBase, AutocompleteMultiSelectionWidget):
    """ContentTree widget that allows multiple selection
    """

    klass = u"contenttree-widget"
    multi_select = True
    display_template = ViewPageTemplateFile('display_multiple.pt')


@implementer(z3c.form.interfaces.IFieldWidget)
def ContentTreeFieldWidget(field, request):
    return z3c.form.widget.FieldWidget(field, ContentTreeWidget(request))


@implementer(z3c.form.interfaces.IFieldWidget)
def MultiContentTreeFieldWidget(field, request):
    return z3c.form.widget.FieldWidget(field, MultiContentTreeWidget(request))
